"""PDF Parser: extract Event Order data from PDF text."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

import pdfplumber

from recon.models import LineItem, EventOrder, MatchTrace


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

    # Check if met
    is_met = "has been met" in text.lower()

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
            function_name = schedule_rental_match.group(3).strip()
            # Clean up function name - remove venue/setup info that comes after
            # Look for common venue names and truncate there
            for venue_marker in ["Brisbane Ballroom", "Business Centre", "Event Centre", "Conference",
                                 "New Farm Room", "Mt Coot-Tha Room", "Classroom", "Theatre", "Buffet", "Flow"]:
                if venue_marker in function_name:
                    function_name = function_name.split(venue_marker)[0].strip()
                    break
            # Also remove trailing numbers (GTD column that got included)
            function_name = re.sub(r"\s+\d+\s*$", "", function_name)
            if function_name:  # Only return if we have a valid function name
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
        return ParsedLine(
            description=line.strip(),
            basis="per_unit",
            qty=qty,
            unit_price=price,
            value=round(qty * price, 2),
            money_type="contracted",
            posts_to="both",
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
            function_name = schedule_rental_match.group(3).strip()
            # Clean up function name - remove venue/setup info that comes after
            for venue_marker in ["Brisbane Ballroom", "Business Centre", "Event Centre", "Conference",
                                 "New Farm Room", "Mt Coot-Tha Room", "Classroom", "Theatre", "Buffet", "Flow"]:
                if venue_marker in function_name:
                    function_name = function_name.split(venue_marker)[0].strip()
                    break
            # Also remove trailing numbers (GTD column that got included)
            function_name = re.sub(r"\s+\d+\s*$", "", function_name)
            if function_name:  # Only return if we have a valid function name
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

        parsed = ParsedLine(
            description=line.strip(),
            basis="per_unit",
            qty=qty,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
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

    # No pattern matched
    return None


# Section markers and their category mappings
SECTION_MARKERS = {
    "menu content": "food",
    "beverage selection": "beverage",
    "additional resources": "resource",
    "security": "other",
    "venue hire": "venue_hire",
    "minimum spend": "venue_hire",
    "audio visual": "av",
}


def _detect_section(text: str) -> Optional[str]:
    """Detect which section a line belongs to based on markers."""
    text_lower = text.lower()
    for marker, category in SECTION_MARKERS.items():
        if marker in text_lower:
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
        # Extract all text
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

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
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

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
            # Extract text for just this day's pages
            day_text = "\n".join(
                pdf.pages[p].extract_text() or ""
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

            for line in day_text.split("\n"):
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

                # Handle package splits
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

            # Extract minimum spend info and calculate venue hire if needed
            min_spend = extract_minimum_spend(day_text)

            if min_spend and not min_spend.is_met:
                # Calculate F&B total from line items
                fb_total = sum(
                    item.value for item in line_items
                    if item.category in ("food", "beverage")
                )

                # Calculate actual shortfall
                calculated_shortfall = max(0, min_spend.amount - fb_total)

                if calculated_shortfall > 0:
                    # Build description with cross-check info
                    desc = f"Minimum F&B Spend Shortfall (${min_spend.amount:,.0f} min - ${fb_total:,.0f} F&B)"
                    if min_spend.stated_shortfall:
                        desc += f" [EO stated: ${min_spend.stated_shortfall:,.0f}]"

                    # Add venue hire line item for the minimum spend shortfall
                    shortfall_item = LineItem(
                        category="venue_hire",
                        type=desc,
                        basis="flat",
                        value=round(calculated_shortfall, 2),
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
