"""PDF Parser: extract Event Order data from PDF text."""

import re
from typing import Any


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
