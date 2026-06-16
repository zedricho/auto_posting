"""PDF Parser: extract Event Order data from PDF text."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import pdfplumber

from recon.models import LineItem, EventOrder, MatchTrace


def _extract_column_text(page) -> str:
    """
    Extract text from a PDF page, handling two-column layouts.

    EO PDFs often have two columns:
    - Left: Menu content, beverage selection, etc.
    - Right: SET UP, resources, etc.

    Standard extraction reads left-to-right across the full width, which
    interleaves content from both columns. This function detects columns
    and extracts left column fully first, then right column, so section
    headers stay with their content.
    """
    words = page.extract_words()
    if not words:
        return page.extract_text() or ""

    # Get page dimensions
    page_width = page.width
    midpoint = page_width / 2

    # Split words into left and right based on their CENTER position
    # (using center avoids edge cases where a word spans the midpoint)
    left_words = [w for w in words if (w['x0'] + w['x1']) / 2 < midpoint]
    right_words = [w for w in words if (w['x0'] + w['x1']) / 2 >= midpoint]

    # Detect two-column layout:
    # Both sides must have substantial content (not just headers/page numbers)
    # We check for content words, not just total count
    min_words_per_column = 20  # Need at least 20 words per column

    is_two_column = len(left_words) >= min_words_per_column and len(right_words) >= min_words_per_column

    if not is_two_column:
        return page.extract_text() or ""

    def reconstruct_text(word_list):
        """Reconstruct text from words, grouping by line."""
        if not word_list:
            return ""

        # Sort by vertical position (top), then horizontal (x0)
        word_list = sorted(word_list, key=lambda w: (w['top'], w['x0']))

        lines = []
        current_line = []
        current_top = None
        line_tolerance = 5  # Words within 5 pts vertically are same line

        for word in word_list:
            if current_top is None or abs(word['top'] - current_top) <= line_tolerance:
                current_line.append(word['text'])
                if current_top is None:
                    current_top = word['top']
            else:
                # New line
                if current_line:
                    lines.append(' '.join(current_line))
                current_line = [word['text']]
                current_top = word['top']

        # Don't forget the last line
        if current_line:
            lines.append(' '.join(current_line))

        return '\n'.join(lines)

    # Extract left column first, then right column
    left_text = reconstruct_text(left_words)
    right_text = reconstruct_text(right_words)

    # Combine: left column content, then right column content
    return left_text + "\n\n" + right_text


@dataclass
class ParsedLine:
    """Intermediate result from parsing a line (before category assignment)."""

    description: str
    basis: Literal["per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense"]
    pax: Optional[int] = None
    qty: Optional[int] = None
    guards: Optional[int] = None
    hours: Optional[float] = None
    unit_price: Optional[float] = None
    value: float = 0.0
    money_type: Literal["contracted", "consumption", "cash"] = "contracted"
    posts_to: Literal["both", "delphi_only"] = "both"
    needs_manual_value: bool = False
    category_override: Optional[str] = None  # Force category regardless of section
    is_package: bool = False  # Day delegate packages need to be split


# Package split percentages (food/beverage/resource)
PACKAGE_SPLITS = {
    "food": 0.90,
    "beverage": 0.05,
    "resource": 0.05,
}


@dataclass
class ParseResult:
    """Full parse result with traces for debugging."""
    event_order: EventOrder
    matched_lines: List[Tuple[str, ParsedLine, MatchTrace]]  # (raw_text, parsed, trace)
    unmatched_lines: List[str]  # Lines that looked like pricing but didn't match


@dataclass
class EventDay:
    """A single day within a multi-day event."""
    day_number: int
    event_order: EventOrder
    page_range: Tuple[int, int]  # (start_page, end_page) 1-indexed


@dataclass
class MinimumSpend:
    """Minimum F&B spend information extracted from EO."""
    amount: float
    is_met: bool
    stated_shortfall: Optional[float] = None  # What the EO says (may have human error)


def extract_headers(text: str) -> Dict[str, Optional[str]]:
    """
    Extract header fields from EO text.

    Returns dict with keys: pm_number, beo_number, event_name, event_date
    Missing fields are None.
    """
    headers: Dict[str, Optional[str]] = {
        "pm_number": None,
        "beo_number": None,
        "event_name": None,
        "event_date": None,
    }

    # Posting Master #: 9353
    pm_match = re.search(r"Posting Master\s*#:\s*(\d+)", text, re.IGNORECASE)
    if pm_match:
        headers["pm_number"] = pm_match.group(1)

    # BEO#: 2895
    beo_match = re.search(r"BEO\s*#:\s*(\d+)", text, re.IGNORECASE)
    if beo_match:
        headers["beo_number"] = beo_match.group(1)

    # Post As: Ultimate Origin Lunch 2026
    name_match = re.search(r"Post As:\s*(.+?)(?:\n|$)", text)
    if name_match:
        headers["event_name"] = name_match.group(1).strip()

    # Event Date: Fri 05 Jun 2026
    date_match = re.search(r"Event Date:\s*(.+?)(?:\n|$)", text)
    if date_match:
        headers["event_date"] = date_match.group(1).strip()

    return headers


def extract_minimum_spend(text: str) -> Optional[MinimumSpend]:
    """
    Extract minimum F&B spend information from EO text.

    Looks for patterns like:
    - "Minimum F&B spend of $30,000.00 required - has been met"
    - "Minimum F&B spend of $30,000.00 required - has not been met - shortfall of $6086.00"
    """
    # Look for minimum spend line
    min_spend_match = re.search(
        r"Minimum\s+F&B\s+spend\s+of\s+\$?([\d,]+\.?\d*)\s*(?:required)?",
        text,
        re.IGNORECASE,
    )
    if not min_spend_match:
        return None

    amount = float(min_spend_match.group(1).replace(",", ""))

    # Check if met - look for various formats:
    # - "has been met"
    # - "- met" (common shorthand)
    # - "- has been met"
    text_lower = text.lower()
    is_met = "has been met" in text_lower or "- met" in text_lower

    # Look for stated shortfall
    shortfall_match = re.search(
        r"shortfall\s+of\s+\$?([\d,]+\.?\d*)",
        text,
        re.IGNORECASE,
    )
    stated_shortfall = None
    if shortfall_match:
        stated_shortfall = float(shortfall_match.group(1).replace(",", ""))

    return MinimumSpend(
        amount=amount,
        is_met=is_met,
        stated_shortfall=stated_shortfall,
    )


def _parse_price(price_str: str) -> float:
    """Parse a price string like '$2,702.63' to float."""
    cleaned = price_str.replace("$", "").replace(",", "")
    return float(cleaned)


def _parse_time_to_hours(start: str, end: str) -> float:
    """Convert time range to hours. E.g., '11:00' to '16:30' = 5.5 hours."""
    start_h, start_m = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    start_mins = start_h * 60 + start_m
    end_mins = end_h * 60 + end_m
    return (end_mins - start_mins) / 60


def parse_line(line: str) -> Optional[ParsedLine]:
    """
    Parse a single line from an EO and extract pricing information.

    Returns ParsedLine if a known pattern is matched, None otherwise.
    """
    line_lower = line.lower()

    # Day delegate package: "Package Name Qty $Price" (per person)
    # E.g., "$89 Half Day Executive Meeting Package AM 15 $89.00"
    # The qty is the number of people, price is per person
    day_package_match = re.search(
        r"(.+?(?:package|pkg).*?)\s+(\d+)\s+\$(\d[\d,]*\.?\d*)\s*$",
        line,
        re.IGNORECASE,
    )
    if day_package_match:
        package_name = day_package_match.group(1).strip()
        qty = int(day_package_match.group(2))
        price_per_person = _parse_price(day_package_match.group(3))
        total_value = round(qty * price_per_person, 2)
        return ParsedLine(
            description=package_name,
            basis="per_person",
            pax=qty,
            unit_price=price_per_person,
            value=total_value,
            money_type="contracted",
            posts_to="both",
            is_package=True,  # Will be split into food/beverage/resource
        )

    # Schedule table row with rental fee: "HH:MM - HH:MM Function Name ... $X.XX"
    # GTD column is NOT a multiplier - it's just guest count
    # Allow optional trailing content after price (e.g., checkmarks in "Inc. Package" column)
    schedule_rental_match = re.search(
        r"^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s+(.+?)\s+\$([\d,]+\.?\d*)",
        line,
    )
    if schedule_rental_match:
        price = _parse_price(schedule_rental_match.group(4))
        # Only match if price is non-zero (skip $.00 rows)
        if price > 0:
            full_text = schedule_rental_match.group(3).strip()
            function_name = full_text
            venue_found = None
            # Clean up function name - remove venue/setup info that comes after
            # Look for common venue names and truncate there
            for venue_marker in ["Brisbane Ballroom", "Business Centre", "Event Centre", "Conference",
                                 "New Farm Room", "Mt Coot-Tha Room", "Classroom", "Theatre", "Buffet", "Flow",
                                 "Paddington Room", "South Bank Room", "Moreton Room", "Ascot", "Teneriffe",
                                 "Level 7", "Level 2", "Green Room"]:
                if venue_marker in function_name:
                    venue_found = venue_marker
                    function_name = function_name.split(venue_marker)[0].strip()
                    break
            # Also remove trailing numbers (GTD column that got included)
            function_name = re.sub(r"\s+\d+\s*$", "", function_name)
            # If function name is empty after cleanup, use the venue name
            if not function_name and venue_found:
                function_name = venue_found
            if function_name:
                return ParsedLine(
                    description=f"{function_name} (Venue Rental)",
                    basis="flat",
                    value=price,
                    money_type="contracted",
                    posts_to="both",
                    category_override="venue_hire",  # Always venue hire regardless of section
                )

    # Check for consumption (no price, needs manual entry)
    if "on consumption" in line_lower:
        desc = re.sub(r"\s*on consumption\s*", "", line, flags=re.IGNORECASE).strip()
        return ParsedLine(
            description=desc,
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )

    # Barista coffee orders - consumption-style, needs manual entry after event
    if "barista" in line_lower and ("coffee" in line_lower or "order" in line_lower):
        return ParsedLine(
            description="Barista Coffee Orders",
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )

    # Check for guest expense / cash (no price, needs manual entry)
    if "at guest expense" in line_lower:
        desc = re.sub(r"\s*at guest expense\s*", "", line, flags=re.IGNORECASE).strip()
        return ParsedLine(
            description=desc,
            basis="guest_expense",
            value=0.0,
            money_type="cash",
            posts_to="delphi_only",
            needs_manual_value=True,
        )

    # Security pattern: N Guards from HH:MM - HH:MM @ $X Per Hour
    security_match = re.search(
        r"(\d+)\s*Guards?\s*(?:from\s*)?(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*@\s*\$?([\d,]+\.?\d*)\s*Per\s*Hour",
        line,
        re.IGNORECASE,
    )
    if security_match:
        guards = int(security_match.group(1))
        hours = _parse_time_to_hours(security_match.group(2), security_match.group(3))
        rate = _parse_price(security_match.group(4))
        return ParsedLine(
            description=line.strip(),
            basis="hourly",
            guards=guards,
            hours=hours,
            unit_price=rate,
            value=round(guards * hours * rate, 2),
            money_type="contracted",
            posts_to="both",
        )

    # Per person pattern: N Pax @ $X (Per Person)
    pax_match = re.search(
        r"(\d+)\s*Pax\s*@\s*\$?([\d,]+\.?\d*)",
        line,
        re.IGNORECASE,
    )
    if pax_match:
        pax = int(pax_match.group(1))
        price = _parse_price(pax_match.group(2))
        return ParsedLine(
            description=line.strip(),
            basis="per_person",
            pax=pax,
            unit_price=price,
            value=round(pax * price, 2),
            money_type="contracted",
            posts_to="both",
        )

    # Flat "For This Event" pattern: @ $X For This Event
    flat_event_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*For This Event",
        line,
        re.IGNORECASE,
    )
    if flat_event_match:
        price = _parse_price(flat_event_match.group(1))
        return ParsedLine(
            description=line.strip(),
            basis="flat",
            value=price,
            money_type="contracted",
            posts_to="both",
        )

    # Per unit pattern: N @ $X Per [unit]
    per_unit_match = re.search(
        r"(\d+)\s*@\s*\$?([\d,]+\.?\d*)\s*Per\s+\w+",
        line,
        re.IGNORECASE,
    )
    if per_unit_match:
        qty = int(per_unit_match.group(1))
        price = _parse_price(per_unit_match.group(2))
        # "Per Bar" items are setup costs, not beverages
        cat_override = "resource" if "per bar" in line.lower() else None
        return ParsedLine(
            description=line.strip(),
            basis="per_unit",
            qty=qty,
            unit_price=price,
            value=round(qty * price, 2),
            money_type="contracted",
            posts_to="both",
            category_override=cat_override,
        )

    # Flat single item pattern: N @ $X or [text] N @ $X or N [text] @ $X Total
    # E.g., "1 @ $500", "XXXX Cartons 1 @ $2,702.63", "1 Infrastructure Charge @ $5,000.00 Total"
    flat_single_match = re.search(
        r"(\d+)\s*(?:[^@]*)?@\s*\$?([\d,]+\.?\d*)(?:\s+Total)?(?:\s|$)",
        line,
        re.IGNORECASE,
    )
    if flat_single_match:
        qty = int(flat_single_match.group(1))
        price = _parse_price(flat_single_match.group(2))
        return ParsedLine(
            description=line.strip(),
            basis="flat",
            qty=qty,
            unit_price=price,
            value=round(qty * price, 2),
            money_type="contracted",
            posts_to="both",
        )

    # Surcharge/fee pattern without leading quantity: text@ $X Total
    # E.g., "surcharge per item@ $135.60 Total"
    surcharge_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Total",
        line,
        re.IGNORECASE,
    )
    if surcharge_match:
        price = _parse_price(surcharge_match.group(1))
        if price > 0:
            return ParsedLine(
                description=line.strip(),
                basis="flat",
                qty=1,
                unit_price=price,
                value=price,
                money_type="contracted",
                posts_to="both",
            )

    # Standalone hourly rate: @ $X Per Hour (needs manual hours/guards entry)
    standalone_hourly_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Per\s*Hour",
        line,
        re.IGNORECASE,
    )
    if standalone_hourly_match:
        rate = _parse_price(standalone_hourly_match.group(1))
        return ParsedLine(
            description=line.strip(),
            basis="hourly",
            unit_price=rate,
            value=0.0,
            money_type="contracted",
            posts_to="both",
            needs_manual_value=True,
        )

    # Standalone per-unit price: @ $X Per [unit] (needs manual qty entry)
    standalone_per_unit_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Per\s+\w+",
        line,
        re.IGNORECASE,
    )
    if standalone_per_unit_match:
        price = _parse_price(standalone_per_unit_match.group(1))
        return ParsedLine(
            description=line.strip(),
            basis="per_unit",
            unit_price=price,
            value=0.0,
            money_type="contracted",
            posts_to="both",
            needs_manual_value=True,
        )

    # Standalone "@ $X Each" pattern (needs manual qty entry)
    # E.g., "@ $55.00 Each" on its own line
    standalone_each_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Each",
        line,
        re.IGNORECASE,
    )
    if standalone_each_match:
        price = _parse_price(standalone_each_match.group(1))
        return ParsedLine(
            description=line.strip(),
            basis="per_unit",
            unit_price=price,
            value=0.0,
            money_type="contracted",
            posts_to="both",
            needs_manual_value=True,
        )

    # No pattern matched
    return None


def parse_line_with_trace(line: str) -> Optional[Tuple[ParsedLine, MatchTrace]]:
    """
    Parse a single line from an EO and extract pricing information with trace metadata.

    Returns tuple of (ParsedLine, MatchTrace) if a known pattern is matched, None otherwise.
    """
    line_lower = line.lower()

    # Day delegate package: "Package Name Qty $Price" (per person)
    # E.g., "$89 Half Day Executive Meeting Package AM 15 $89.00"
    day_package_match = re.search(
        r"(.+?(?:package|pkg).*?)\s+(\d+)\s+\$(\d[\d,]*\.?\d*)\s*$",
        line,
        re.IGNORECASE,
    )
    if day_package_match:
        package_name = day_package_match.group(1).strip()
        qty = int(day_package_match.group(2))
        price_per_person = _parse_price(day_package_match.group(3))
        total_value = round(qty * price_per_person, 2)
        parsed = ParsedLine(
            description=package_name,
            basis="per_person",
            pax=qty,
            unit_price=price_per_person,
            value=total_value,
            money_type="contracted",
            posts_to="both",
            is_package=True,  # Will be split into food/beverage/resource
        )
        trace = MatchTrace(
            pattern_name="day_package",
            matched_text=line.strip(),
            extracted={"package": package_name, "qty": qty, "price_per_person": price_per_person},
            calculation=f"{qty} × ${price_per_person:.2f} (split: 90% food, 5% bev, 5% res)",
            value=total_value,
        )
        return (parsed, trace)

    # Schedule table row with rental fee: "HH:MM - HH:MM Function Name ... $X.XX"
    # GTD column is NOT a multiplier - it's just guest count
    # Allow optional trailing content after price (e.g., checkmarks in "Inc. Package" column)
    schedule_rental_match = re.search(
        r"^(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s+(.+?)\s+\$([\d,]+\.?\d*)",
        line,
    )
    if schedule_rental_match:
        price = _parse_price(schedule_rental_match.group(4))
        # Only match if price is non-zero (skip $.00 rows)
        if price > 0:
            full_text = schedule_rental_match.group(3).strip()
            function_name = full_text
            venue_found = None
            # Clean up function name - remove venue/setup info that comes after
            for venue_marker in ["Brisbane Ballroom", "Business Centre", "Event Centre", "Conference",
                                 "New Farm Room", "Mt Coot-Tha Room", "Classroom", "Theatre", "Buffet", "Flow",
                                 "Paddington Room", "South Bank Room", "Moreton Room", "Ascot", "Teneriffe",
                                 "Level 7", "Level 2", "Green Room"]:
                if venue_marker in function_name:
                    venue_found = venue_marker
                    function_name = function_name.split(venue_marker)[0].strip()
                    break
            # Also remove trailing numbers (GTD column that got included)
            function_name = re.sub(r"\s+\d+\s*$", "", function_name)
            # If function name is empty after cleanup, use the venue name
            if not function_name and venue_found:
                function_name = venue_found
            if function_name:
                parsed = ParsedLine(
                    description=f"{function_name} (Venue Rental)",
                    basis="flat",
                    value=price,
                    money_type="contracted",
                    posts_to="both",
                    category_override="venue_hire",  # Always venue hire regardless of section
                )
                trace = MatchTrace(
                    pattern_name="schedule_rental",
                    matched_text=line.strip(),
                    extracted={"function": function_name, "price": price},
                    calculation=f"${price:,.2f} flat (venue rental → venue_hire)",
                    value=price,
                )
                return (parsed, trace)

    # Check for consumption (no price, needs manual entry)
    if "on consumption" in line_lower:
        desc = re.sub(r"\s*on consumption\s*", "", line, flags=re.IGNORECASE).strip()
        parsed = ParsedLine(
            description=desc,
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="consumption",
            matched_text=line.strip(),
            extracted={},
            calculation="Manual entry required",
            value=0.0,
        )
        return (parsed, trace)

    # Barista coffee orders - consumption-style, needs manual entry after event
    if "barista" in line_lower and ("coffee" in line_lower or "order" in line_lower):
        parsed = ParsedLine(
            description="Barista Coffee Orders",
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="barista",
            matched_text=line.strip(),
            extracted={},
            calculation="Manual entry required (post-event)",
            value=0.0,
        )
        return (parsed, trace)

    # Check for guest expense / cash (no price, needs manual entry)
    if "at guest expense" in line_lower:
        desc = re.sub(r"\s*at guest expense\s*", "", line, flags=re.IGNORECASE).strip()
        parsed = ParsedLine(
            description=desc,
            basis="guest_expense",
            value=0.0,
            money_type="cash",
            posts_to="delphi_only",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="guest_expense",
            matched_text=line.strip(),
            extracted={},
            calculation="Manual entry required",
            value=0.0,
        )
        return (parsed, trace)

    # Security pattern: N Guards from HH:MM - HH:MM @ $X Per Hour
    security_match = re.search(
        r"(\d+)\s*Guards?\s*(?:from\s*)?(\d{1,2}:\d{2})\s*[-–]\s*(\d{1,2}:\d{2})\s*@\s*\$?([\d,]+\.?\d*)\s*Per\s*Hour",
        line,
        re.IGNORECASE,
    )
    if security_match:
        guards = int(security_match.group(1))
        hours = _parse_time_to_hours(security_match.group(2), security_match.group(3))
        rate = _parse_price(security_match.group(4))
        value = round(guards * hours * rate, 2)

        parsed = ParsedLine(
            description=line.strip(),
            basis="hourly",
            guards=guards,
            hours=hours,
            unit_price=rate,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="hourly",
            matched_text=security_match.group(0),
            extracted={"guards": guards, "hours": hours, "rate": rate},
            calculation=f"{guards} × {hours} × ${rate:.2f}",
            value=value,
        )
        return (parsed, trace)

    # Per person pattern: N Pax @ $X (Per Person)
    pax_match = re.search(
        r"(\d+)\s*Pax\s*@\s*\$?([\d,]+\.?\d*)",
        line,
        re.IGNORECASE,
    )
    if pax_match:
        pax = int(pax_match.group(1))
        price = _parse_price(pax_match.group(2))
        value = round(pax * price, 2)

        parsed = ParsedLine(
            description=line.strip(),
            basis="per_person",
            pax=pax,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="per_person",
            matched_text=pax_match.group(0),
            extracted={"pax": pax, "price": price},
            calculation=f"{pax} × ${price:.2f}",
            value=value,
        )
        return (parsed, trace)

    # Flat "For This Event" pattern: @ $X For This Event
    flat_event_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*For This Event",
        line,
        re.IGNORECASE,
    )
    if flat_event_match:
        price = _parse_price(flat_event_match.group(1))

        parsed = ParsedLine(
            description=line.strip(),
            basis="flat",
            value=price,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="flat",
            matched_text=flat_event_match.group(0),
            extracted={"price": price},
            calculation=f"${price:,.2f} flat",
            value=price,
        )
        return (parsed, trace)

    # Per unit pattern: N @ $X Per [unit]
    per_unit_match = re.search(
        r"(\d+)\s*@\s*\$?([\d,]+\.?\d*)\s*Per\s+\w+",
        line,
        re.IGNORECASE,
    )
    if per_unit_match:
        qty = int(per_unit_match.group(1))
        price = _parse_price(per_unit_match.group(2))
        value = round(qty * price, 2)
        # "Per Bar" items are setup costs, not beverages
        cat_override = "resource" if "per bar" in line.lower() else None

        parsed = ParsedLine(
            description=line.strip(),
            basis="per_unit",
            qty=qty,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
            category_override=cat_override,
        )
        trace = MatchTrace(
            pattern_name="per_unit",
            matched_text=per_unit_match.group(0),
            extracted={"qty": qty, "price": price},
            calculation=f"{qty} × ${price:.2f}",
            value=value,
        )
        return (parsed, trace)

    # Flat single item pattern: N @ $X or [text] N @ $X or N [text] @ $X Total
    # E.g., "1 @ $500", "XXXX Cartons 1 @ $2,702.63", "1 Infrastructure Charge @ $5,000.00 Total"
    flat_single_match = re.search(
        r"(\d+)\s*(?:[^@]*)?@\s*\$?([\d,]+\.?\d*)(?:\s+Total)?(?:\s|$)",
        line,
        re.IGNORECASE,
    )
    if flat_single_match:
        qty = int(flat_single_match.group(1))
        price = _parse_price(flat_single_match.group(2))
        value = round(qty * price, 2)

        parsed = ParsedLine(
            description=line.strip(),
            basis="flat",
            qty=qty,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="flat",
            matched_text=flat_single_match.group(0),
            extracted={"qty": qty, "price": price},
            calculation=f"{qty} × ${price:.2f}",
            value=value,
        )
        return (parsed, trace)

    # Standalone hourly rate: @ $X Per Hour (needs manual hours/guards entry)
    standalone_hourly_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Per\s*Hour",
        line,
        re.IGNORECASE,
    )
    if standalone_hourly_match:
        rate = _parse_price(standalone_hourly_match.group(1))
        parsed = ParsedLine(
            description=line.strip(),
            basis="hourly",
            unit_price=rate,
            value=0.0,
            money_type="contracted",
            posts_to="both",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="hourly_rate_only",
            matched_text=standalone_hourly_match.group(0),
            extracted={"rate": rate},
            calculation=f"${rate:.2f}/hour × ? hours (needs manual entry)",
            value=0.0,
        )
        return (parsed, trace)

    # Standalone per-unit price: @ $X Per [unit] (needs manual qty entry)
    standalone_per_unit_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Per\s+\w+",
        line,
        re.IGNORECASE,
    )
    if standalone_per_unit_match:
        price = _parse_price(standalone_per_unit_match.group(1))
        parsed = ParsedLine(
            description=line.strip(),
            basis="per_unit",
            unit_price=price,
            value=0.0,
            money_type="contracted",
            posts_to="both",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="per_unit_rate_only",
            matched_text=standalone_per_unit_match.group(0),
            extracted={"price": price},
            calculation=f"${price:.2f} × ? qty (needs manual entry)",
            value=0.0,
        )
        return (parsed, trace)

    # Standalone "@ $X Each" pattern (needs manual qty entry)
    standalone_each_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*Each",
        line,
        re.IGNORECASE,
    )
    if standalone_each_match:
        price = _parse_price(standalone_each_match.group(1))
        parsed = ParsedLine(
            description=line.strip(),
            basis="per_unit",
            unit_price=price,
            value=0.0,
            money_type="contracted",
            posts_to="both",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="each_rate_only",
            matched_text=standalone_each_match.group(0),
            extracted={"price": price},
            calculation=f"${price:.2f} × ? qty (needs manual entry)",
            value=0.0,
        )
        return (parsed, trace)

    # No pattern matched
    return None


# Section markers and their category mappings
SECTION_MARKERS = {
    "menu content": "food",
    "beverage selection": "beverage",
    "additional resources": "resource",
    "set up": "resource",
    "setup": "resource",  # Alternative without space
    "security": "other",
    "venue hire": "venue_hire",
    "minimum spend": "venue_hire",
    "audio visual": "av",
}


def _detect_section(text: str) -> Optional[str]:
    """Detect which section a line belongs to based on markers.

    Only matches true section headers, not incidental occurrences of marker text.
    Section headers are typically standalone or at the start of a line, like:
    - "SET UP" (standalone)
    - "MENU CONTENT" (standalone)

    We avoid matching:
    - "Existing Set Up" in schedule table rows
    - "Set Up - Something" which is content, not a header
    - Lines that are clearly content (start with "Serve Time:", prices, etc.)
    """
    text_lower = text.lower().strip()

    # Skip schedule table rows (start with time like "07:00" or "7:00")
    if re.match(r"^\d{1,2}:\d{2}", text_lower):
        return None

    # Skip lines that are clearly content, not headers
    content_prefixes = ["serve time", "served", "dietaries", "notes", "client providing"]
    for prefix in content_prefixes:
        if text_lower.startswith(prefix):
            return None

    for marker, category in SECTION_MARKERS.items():
        if marker not in text_lower:
            continue

        # "set up" requires special handling - only match true headers
        if marker in ["set up", "setup"]:
            # Skip "Existing Set Up" (schedule table)
            if "existing set up" in text_lower:
                continue
            # Skip "Set Up - Something" (content description, not header)
            if re.search(r"set\s*up\s*-\s*\w", text_lower):
                continue
            # Skip if line contains other content indicators
            if "serve time" in text_lower or "pax" in text_lower:
                continue
            # Only match if "SET UP" appears standalone (header, not part of content)
            # Must be at end of line or followed only by whitespace/column content
            if text_lower == "set up" or text_lower.endswith(" set up"):
                return category
            continue

        # For other markers, check if they appear prominently
        if text_lower.startswith(marker):
            return category

        # Menu content, beverage selection are distinct enough to match anywhere
        if marker in ["menu content", "beverage selection", "additional resources"]:
            return category

    return None


def parse_pdf(pdf_path: Union[str, Path]) -> EventOrder:
    """
    Parse an EO PDF and extract all data.

    Returns an EventOrder with extracted headers and line items.
    Line items needing manual values are flagged with needs_manual_value=True.
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        # Extract all text using column-aware extraction
        full_text = "\n".join(_extract_column_text(page) for page in pdf.pages)

    # Extract headers
    headers = extract_headers(full_text)

    # Parse event date if present
    event_date = None
    if headers["event_date"]:
        try:
            # Try parsing "Fri 05 Jun 2026" format
            event_date = datetime.strptime(
                headers["event_date"], "%a %d %b %Y"
            ).date()
        except ValueError:
            pass  # Leave as None if unparseable

    # Parse line items
    line_items: List[LineItem] = []
    current_section: Optional[str] = None

    for line in full_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check if this line is a section header
        detected_section = _detect_section(line)
        if detected_section:
            current_section = detected_section
            continue

        # Skip if we haven't found a section yet
        if current_section is None:
            continue

        # Try to parse the line
        parsed = parse_line(line)
        if parsed is None:
            continue

        # Determine category (use override if present)
        category = parsed.category_override or current_section

        # Handle package splits (food/beverage/resource)
        if parsed.is_package:
            for split_category, split_pct in PACKAGE_SPLITS.items():
                split_value = round(parsed.value * split_pct, 2)
                item = LineItem(
                    category=split_category,
                    type=f"{parsed.description} ({int(split_pct * 100)}%)",
                    basis=parsed.basis,
                    pax=parsed.pax,
                    qty=parsed.qty,
                    guards=parsed.guards,
                    hours=parsed.hours,
                    unit_price=parsed.unit_price,
                    value=split_value,
                    money_type=parsed.money_type,
                    posts_to=parsed.posts_to,
                    needs_manual_value=parsed.needs_manual_value,
                )
                line_items.append(item)
        else:
            # Standard single line item
            item = LineItem(
                category=category,
                type=parsed.description,
                basis=parsed.basis,
                pax=parsed.pax,
                qty=parsed.qty,
                guards=parsed.guards,
                hours=parsed.hours,
                unit_price=parsed.unit_price,
                value=parsed.value,
                money_type=parsed.money_type,
                posts_to=parsed.posts_to,
                needs_manual_value=parsed.needs_manual_value,
            )
            line_items.append(item)

    return EventOrder(
        pm_number=headers["pm_number"] or "",
        beo_number=headers["beo_number"] or "",
        event_name=headers["event_name"] or "",
        event_date=event_date,
        line_items=line_items,
    )


# Keywords that suggest a line might be pricing-related
PRICING_KEYWORDS = ["$", "@", "pax", "per ", "consumption", "expense", "hire", "fee"]


def _looks_like_pricing(line: str) -> bool:
    """Check if a line looks like it might contain pricing info."""
    line_lower = line.lower()
    return any(kw in line_lower for kw in PRICING_KEYWORDS)


def parse_pdf_with_traces(pdf_path: Union[str, Path]) -> ParseResult:
    """
    Parse an EO PDF and return detailed trace information.

    Returns ParseResult with:
    - event_order: The parsed EventOrder
    - matched_lines: List of (raw_text, ParsedLine, MatchTrace) tuples
    - unmatched_lines: Lines that look like pricing but didn't match any pattern
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        # Use column-aware extraction
        full_text = "\n".join(_extract_column_text(page) for page in pdf.pages)

    # Extract headers
    headers = extract_headers(full_text)

    # Parse event date if present
    event_date = None
    if headers["event_date"]:
        try:
            event_date = datetime.strptime(
                headers["event_date"], "%a %d %b %Y"
            ).date()
        except ValueError:
            pass

    # Parse line items with traces
    line_items: List[LineItem] = []
    matched_lines: List[Tuple[str, ParsedLine, MatchTrace]] = []
    unmatched_lines: List[str] = []
    current_section: Optional[str] = None
    context_line: Optional[str] = None  # Previous non-pricing line for context

    for line in full_text.split("\n"):
        line = line.strip()
        if not line:
            continue

        # Check if this line is a section header
        detected_section = _detect_section(line)
        if detected_section:
            current_section = detected_section
            context_line = None  # Reset context on new section
            continue

        # Skip if we haven't found a section yet
        if current_section is None:
            continue

        # Try to parse the line with trace
        result = parse_line_with_trace(line)
        if result is not None:
            parsed, trace = result

            # For standalone patterns, use context from previous line
            item_type = parsed.description
            if parsed.needs_manual_value and context_line:
                item_type = f"{context_line}: {line}"

            # Determine category (use override if present)
            category = parsed.category_override or current_section

            # Handle package splits (food/beverage/resource)
            if parsed.is_package:
                for split_category, split_pct in PACKAGE_SPLITS.items():
                    split_value = round(parsed.value * split_pct, 2)
                    item = LineItem(
                        category=split_category,
                        type=f"{item_type} ({int(split_pct * 100)}%)",
                        basis=parsed.basis,
                        pax=parsed.pax,
                        qty=parsed.qty,
                        guards=parsed.guards,
                        hours=parsed.hours,
                        unit_price=parsed.unit_price,
                        value=split_value,
                        money_type=parsed.money_type,
                        posts_to=parsed.posts_to,
                        needs_manual_value=parsed.needs_manual_value,
                    )
                    line_items.append(item)
            else:
                # Standard single line item
                item = LineItem(
                    category=category,
                    type=item_type,
                    basis=parsed.basis,
                    pax=parsed.pax,
                    qty=parsed.qty,
                    guards=parsed.guards,
                    hours=parsed.hours,
                    unit_price=parsed.unit_price,
                    value=parsed.value,
                    money_type=parsed.money_type,
                    posts_to=parsed.posts_to,
                    needs_manual_value=parsed.needs_manual_value,
                )
                line_items.append(item)
            matched_lines.append((line, parsed, trace))
            context_line = None  # Reset context after using it
        elif _looks_like_pricing(line):
            # Line looks like it might be pricing but didn't match
            unmatched_lines.append(line)
            context_line = None  # Reset context
        else:
            # Non-pricing line - save as context for next pricing line
            context_line = line

    event_order = EventOrder(
        pm_number=headers["pm_number"] or "",
        beo_number=headers["beo_number"] or "",
        event_name=headers["event_name"] or "",
        event_date=event_date,
        line_items=line_items,
    )

    return ParseResult(
        event_order=event_order,
        matched_lines=matched_lines,
        unmatched_lines=unmatched_lines,
    )


def _detect_day_boundaries(pdf_path: Union[str, Path]) -> List[Tuple[int, int, str, str, str]]:
    """
    Detect day boundaries in a multi-day event PDF.

    Returns list of (start_page, end_page, beo_number, event_date, day_label) tuples.
    Pages are 0-indexed.
    """
    pdf_path = Path(pdf_path)
    days = []

    with pdfplumber.open(pdf_path) as pdf:
        current_day_start = 0
        current_beo = None
        current_date = None
        current_day_label = None

        for page_idx, page in enumerate(pdf.pages):
            text = page.extract_text() or ""

            # Look for BEO number
            beo_match = re.search(r"BEO\s*#:\s*(\d+)", text, re.IGNORECASE)
            page_beo = beo_match.group(1) if beo_match else None

            # Look for Event Date
            date_match = re.search(r"Event Date:\s*(.+?)(?:\n|$)", text)
            page_date = date_match.group(1).strip() if date_match else None

            # Look for Day X marker
            day_match = re.search(r"\bDay\s+(\d+)\b", text)
            page_day_label = f"Day {day_match.group(1)}" if day_match else None

            # If we see a new BEO number, this is a new day
            if page_beo and page_beo != current_beo:
                # Save previous day if we have one
                if current_beo is not None:
                    days.append((
                        current_day_start,
                        page_idx - 1,
                        current_beo,
                        current_date or "",
                        current_day_label or f"Day {len(days) + 1}",
                    ))
                # Start new day
                current_day_start = page_idx
                current_beo = page_beo
                current_date = page_date
                current_day_label = page_day_label
            elif current_beo is None and page_beo:
                # First day
                current_beo = page_beo
                current_date = page_date
                current_day_label = page_day_label

        # Don't forget the last day
        if current_beo is not None:
            days.append((
                current_day_start,
                len(pdf.pages) - 1,
                current_beo,
                current_date or "",
                current_day_label or f"Day {len(days) + 1}",
            ))

    return days


def parse_pdf_multiday(pdf_path: Union[str, Path]) -> List[EventDay]:
    """
    Parse a multi-day event PDF and return a list of EventDay objects.

    Each day is parsed separately with its own BEO number, date, and line items.
    For single-day events, returns a list with one EventDay.
    """
    pdf_path = Path(pdf_path)

    # Detect day boundaries
    day_boundaries = _detect_day_boundaries(pdf_path)

    if not day_boundaries:
        # Fallback: treat as single day
        event_order = parse_pdf(pdf_path)
        return [EventDay(
            day_number=1,
            event_order=event_order,
            page_range=(1, 1),
        )]

    event_days = []

    with pdfplumber.open(pdf_path) as pdf:
        for day_idx, (start_page, end_page, beo_number, event_date_str, day_label) in enumerate(day_boundaries):
            # Extract text for just this day's pages using column-aware extraction
            day_text = "\n".join(
                _extract_column_text(pdf.pages[p])
                for p in range(start_page, end_page + 1)
            )

            # Parse event date
            event_date = None
            if event_date_str:
                try:
                    # Try parsing "Wed, 10 Jun 2026" or "Fri 05 Jun 2026" format
                    for fmt in ["%a, %d %b %Y", "%a %d %b %Y"]:
                        try:
                            event_date = datetime.strptime(event_date_str, fmt).date()
                            break
                        except ValueError:
                            continue
                except Exception:
                    pass

            # Extract PM number and event name from this day's text
            headers = extract_headers(day_text)

            # Parse line items for this day
            line_items: List[LineItem] = []
            current_section: Optional[str] = None
            context_lines: List[str] = []  # Track recent non-parsed lines for context

            for line in day_text.split("\n"):
                line = line.strip()
                if not line:
                    continue

                # Check if this line is a section header
                detected_section = _detect_section(line)
                if detected_section:
                    current_section = detected_section
                    context_lines = []  # Reset context on section change
                    continue

                # Try to parse the line
                parsed = parse_line(line)
                if parsed is None:
                    # Track non-parsed lines as potential context/headers
                    # Only keep lines that look like actual headers:
                    # - Not bullet points
                    # - Not times
                    # - Not common boilerplate
                    # - Reasonable length (5-60 chars)
                    # - Contains letters (not just numbers/symbols)
                    is_header_candidate = (
                        not line.startswith(("\uf0b7", "•", "-", "o ", "*")) and
                        not re.match(r"^\d{1,2}:\d{2}", line) and
                        5 <= len(line) <= 60 and
                        re.search(r"[a-zA-Z]", line) and
                        not any(skip in line.lower() for skip in [
                            "event order", "organization", "signature", "date printed",
                            "deactivated", "please note", "as per", "ready for service"
                        ])
                    )
                    if is_header_candidate:
                        context_lines.append(line)
                    # Keep only last 3 context lines
                    context_lines = context_lines[-3:]
                    continue

                # Determine category (use override if present)
                # Items with category_override can be processed even before a section is detected
                # (e.g., venue rentals in the schedule table at the top of the page)
                if parsed.category_override:
                    category = parsed.category_override
                elif current_section is None:
                    # Skip lines without override if we haven't found a section yet
                    continue
                else:
                    category = current_section

                # Content-based category overrides to fix two-column PDF interleaving issues
                line_lower = line.lower()

                # Coffee always goes to food, not beverage
                if "coffee" in line_lower and category == "beverage":
                    category = "food"

                # Booth fees, exhibition items, Per Day charges, infrastructure, furniture → resource (setup costs)
                if category == "beverage":
                    if any(kw in line_lower for kw in ["per booth", "booth fee", "exhibition", "per day", "wifi", "infrastructure", "chair", "table", "linen", "napkin", "tablecloth"]):
                        category = "resource"
                    # Simple price patterns like "1 @ $X.00" without food/beverage keywords → resource
                    # These are typically setup/IT charges that got miscategorized due to column interleaving
                    elif re.match(r"^\d+\s*@\s*\$[\d,]+\.?\d*$", line.strip()):
                        # It's a simple "N @ $X" pattern - likely a setup charge, not food/beverage
                        category = "resource"

                # Crew meals and food items with "Pax @" in wrong section → food
                if category == "resource":
                    if "pax @" in line_lower and any(kw in line_lower for kw in ["crew", "meal", "menu", "per person"]):
                        category = "food"

                # Build description, potentially using context for better naming
                description = parsed.description

                # For resource items with generic descriptions (like "1 @ $200.00 Per Day"),
                # try to find a better name from context (preceding header lines)
                if category == "resource" and context_lines:
                    # Look for a header-like line in context (WiFi, IT services, etc.)
                    for ctx in reversed(context_lines):
                        ctx_clean = ctx.strip()
                        # Skip lines that are just times, prices, or too short
                        if len(ctx_clean) > 3 and not re.match(r"^\d", ctx_clean):
                            # Use this as the description prefix
                            description = f"{ctx_clean}: {parsed.description}"
                            break

                # Clear context after using it for a priced item
                context_lines = []

                # Handle package splits
                if parsed.is_package:
                    for split_category, split_pct in PACKAGE_SPLITS.items():
                        split_value = round(parsed.value * split_pct, 2)
                        item = LineItem(
                            category=split_category,
                            type=f"{description} ({int(split_pct * 100)}%)",
                            basis=parsed.basis,
                            pax=parsed.pax,
                            qty=parsed.qty,
                            guards=parsed.guards,
                            hours=parsed.hours,
                            unit_price=parsed.unit_price,
                            value=split_value,
                            money_type=parsed.money_type,
                            posts_to=parsed.posts_to,
                            needs_manual_value=parsed.needs_manual_value,
                        )
                        line_items.append(item)
                else:
                    item = LineItem(
                        category=category,
                        type=description,
                        basis=parsed.basis,
                        pax=parsed.pax,
                        qty=parsed.qty,
                        guards=parsed.guards,
                        hours=parsed.hours,
                        unit_price=parsed.unit_price,
                        value=parsed.value,
                        money_type=parsed.money_type,
                        posts_to=parsed.posts_to,
                        needs_manual_value=parsed.needs_manual_value,
                    )
                    line_items.append(item)

            # Extract minimum spend info and calculate venue hire if needed
            min_spend = extract_minimum_spend(day_text)

            if min_spend and not min_spend.is_met:
                # Check if we already have a venue_hire item for the shortfall
                # (it may have been parsed as a line item already)
                # Check both by keyword and by matching the shortfall value
                shortfall_value_to_check = min_spend.stated_shortfall or 0
                existing_shortfall = any(
                    item.category == "venue_hire" and (
                        "shortfall" in item.type.lower() or
                        "minimum" in item.type.lower() or
                        abs(item.value - shortfall_value_to_check) < 1  # Same value
                    )
                    for item in line_items
                )

                if not existing_shortfall:
                    # Calculate F&B total from line items (for reference)
                    fb_total = sum(
                        item.value for item in line_items
                        if item.category in ("food", "beverage")
                    )

                    # Use stated shortfall as primary value (it's authoritative from the EO)
                    # Fall back to calculated shortfall only if stated isn't available
                    if min_spend.stated_shortfall is not None:
                        shortfall_value = min_spend.stated_shortfall
                        desc = f"Minimum F&B Spend Shortfall (${min_spend.amount:,.0f} min, shortfall ${shortfall_value:,.0f})"
                        # Add calculated as cross-check note if different
                        calculated_shortfall = max(0, min_spend.amount - fb_total)
                        if abs(calculated_shortfall - shortfall_value) > 1:
                            desc += f" [Calculated: ${calculated_shortfall:,.0f}]"
                    else:
                        # No stated shortfall, calculate it
                        shortfall_value = max(0, min_spend.amount - fb_total)
                        desc = f"Minimum F&B Spend Shortfall (${min_spend.amount:,.0f} min - ${fb_total:,.0f} F&B)"

                    if shortfall_value > 0:
                        # Add venue hire line item for the minimum spend shortfall
                        shortfall_item = LineItem(
                            category="venue_hire",
                            type=desc,
                            basis="flat",
                            value=round(shortfall_value, 2),
                            money_type="contracted",
                            posts_to="both",
                        )
                        line_items.append(shortfall_item)

            event_order = EventOrder(
                pm_number=headers["pm_number"] or "",
                beo_number=beo_number,
                event_name=headers["event_name"] or "",
                event_date=event_date,
                line_items=line_items,
            )

            event_days.append(EventDay(
                day_number=day_idx + 1,
                event_order=event_order,
                page_range=(start_page + 1, end_page + 1),  # Convert to 1-indexed
            ))

    return event_days
