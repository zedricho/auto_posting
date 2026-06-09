"""Pydantic models for Event Order data."""

from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel


@dataclass
class MatchTrace:
    """Metadata about how a line was parsed."""
    pattern_name: str          # "per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense"
    matched_text: str          # The raw regex match
    extracted: Dict[str, Any]  # {"pax": 1174, "price": 105.0}
    calculation: str           # "1174 × $105.00"
    value: float               # Computed value


class LineItem(BaseModel):
    """A single line item from an Event Order."""

    category: Literal["food", "beverage", "resource", "other", "venue_hire", "av"]
    type: str  # e.g. "Plated Meal - 3 Courses"
    basis: Literal[
        "per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense", "external"
    ]

    # Quantity fields (optional depending on basis)
    pax: Optional[int] = None
    qty: Optional[int] = None
    guards: Optional[int] = None
    hours: Optional[float] = None

    unit_price: Optional[float] = None
    value: float  # Computed or manually entered

    money_type: Literal["contracted", "consumption", "cash", "external"]
    posts_to: Literal["both", "delphi_only", "none"]

    needs_manual_value: bool = False  # True for consumption/cash lines
    source: Optional[str] = None  # "keyed_post_event", "pos", etc.


class EventOrder(BaseModel):
    """A complete Event Order (one BEO)."""

    pm_number: str
    beo_number: str
    event_name: str
    event_date: Optional[date] = None
    line_items: List[LineItem] = []


class CategoryTotals(BaseModel):
    """Totals for a single category."""

    category: str
    delphi_total: float  # Includes cash
    opera_total: float  # Excludes cash


class WorksheetOutput(BaseModel):
    """Complete worksheet output with all totals."""

    event: EventOrder
    totals: List[CategoryTotals]
    delphi_grand_total: float
    opera_grand_total: float
