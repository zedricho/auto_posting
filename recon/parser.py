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


@dataclass
class ParseResult:
    """Full parse result with traces for debugging."""
    event_order: EventOrder
    matched_lines: List[Tuple[str, ParsedLine, MatchTrace]]  # (raw_text, parsed, trace)
    unmatched_lines: List[str]  # Lines that looked like pricing but didn't match


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

    # Flat single item pattern: 1 @ $X (no "Per" or "For This Event")
    flat_single_match = re.search(
        r"(\d+)\s*@\s*\$?([\d,]+\.?\d*)(?:\s|$)",
        line,
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
        )
        trace = MatchTrace(
            pattern_name="day_package",
            matched_text=line.strip(),
            extracted={"package": package_name, "qty": qty, "price_per_person": price_per_person},
            calculation=f"{qty} × ${price_per_person:.2f}",
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
                )
                trace = MatchTrace(
                    pattern_name="schedule_rental",
                    matched_text=line.strip(),
                    extracted={"function": function_name, "price": price},
                    calculation=f"${price:,.2f} flat (venue rental)",
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

    # Flat single item pattern: 1 @ $X (no "Per" or "For This Event")
    flat_single_match = re.search(
        r"(\d+)\s*@\s*\$?([\d,]+\.?\d*)(?:\s|$)",
        line,
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

        # Convert ParsedLine to LineItem
        item = LineItem(
            category=current_section,
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

            # Convert ParsedLine to LineItem
            item = LineItem(
                category=current_section,
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
