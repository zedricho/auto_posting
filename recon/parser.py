"""PDF Parser: extract Event Order data from PDF text."""

import re
from dataclasses import dataclass
from typing import Any, Literal


@dataclass
class ParsedLine:
    """Intermediate result from parsing a line (before category assignment)."""

    description: str
    basis: Literal["per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense"]
    pax: int | None = None
    qty: int | None = None
    guards: int | None = None
    hours: float | None = None
    unit_price: float | None = None
    value: float = 0.0
    money_type: Literal["contracted", "consumption", "cash"] = "contracted"
    posts_to: Literal["both", "delphi_only"] = "both"
    needs_manual_value: bool = False


def extract_headers(text: str) -> dict[str, str | None]:
    """
    Extract header fields from EO text.

    Returns dict with keys: pm_number, beo_number, event_name, event_date
    Missing fields are None.
    """
    headers: dict[str, str | None] = {
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


def parse_line(line: str) -> ParsedLine | None:
    """
    Parse a single line from an EO and extract pricing information.

    Returns ParsedLine if a known pattern is matched, None otherwise.
    """
    line_lower = line.lower()

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

    # No pattern matched
    return None
