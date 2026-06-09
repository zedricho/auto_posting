# Event Order Reconciliation Tool — MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Streamlit app that extracts EO PDFs, computes Delphi/Opera totals, generates worksheets, and reconciles against Delphi reports.

**Architecture:** Four-step wizard (Upload → Complete Values → Generate → Reconcile) with deterministic parsing. Core modules: models (Pydantic schemas), parser (PDF extraction), builder (totals + Excel), reconciler (diff + diagnostics). All money computation is pure Python — no LLM.

**Tech Stack:** Python 3.11+, Streamlit, pdfplumber, Pydantic v2, openpyxl, pandas, pytest

---

## File Structure

```
event-recon/
├── app.py                      # Streamlit wizard entry point
├── recon/
│   ├── __init__.py             # Package exports
│   ├── models.py               # Pydantic schemas (LineItem, EventOrder, etc.)
│   ├── parser.py               # PDF text extraction + pattern matching
│   ├── builder.py              # Compute totals, generate Excel workbook
│   ├── reconciler.py           # Compare worksheet vs Delphi, diagnostics
│   └── delphi_adapter.py       # Parse Delphi Excel export
├── tests/
│   ├── __init__.py
│   ├── test_models.py          # Schema validation tests
│   ├── test_builder_golden.py  # Golden test: BEO 2895 totals
│   ├── test_parser.py          # Pattern matching tests
│   ├── test_reconciler.py      # Discrepancy detection tests
│   └── fixtures/
│       └── beo_2895.json       # Golden test fixture
├── .streamlit/
│   └── secrets.toml.example    # Auth password template
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## Task 1: Project Setup

**Files:**
- Create: `requirements.txt`
- Create: `pyproject.toml`
- Create: `recon/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: Create requirements.txt**

```
streamlit>=1.28
pdfplumber>=0.10
pydantic>=2.0
openpyxl>=3.1
pandas>=2.0
pytest>=7.0
```

- [ ] **Step 2: Create pyproject.toml**

```toml
[project]
name = "event-recon"
version = "0.1.0"
description = "Event Order Reconciliation Tool for The Star Brisbane"
requires-python = ">=3.11"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
```

- [ ] **Step 3: Create package init files**

Create `recon/__init__.py`:
```python
"""Event Order Reconciliation Tool."""
```

Create `tests/__init__.py`:
```python
"""Tests for event-recon."""
```

- [ ] **Step 4: Create virtual environment and install dependencies**

Run:
```bash
cd /Users/zakedrich/Documents/work/coding/auto_posting
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Expected: Dependencies install successfully

- [ ] **Step 5: Verify pytest runs**

Run: `pytest --collect-only`
Expected: "no tests ran" (no tests yet, but pytest works)

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pyproject.toml recon/ tests/
git commit -m "chore: project setup with dependencies"
```

---

## Task 2: Pydantic Models

**Files:**
- Create: `recon/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write test for LineItem model**

Create `tests/test_models.py`:
```python
import pytest
from datetime import date
from recon.models import LineItem, EventOrder, CategoryTotals, WorksheetOutput


class TestLineItem:
    def test_contracted_line_item(self):
        """A contracted line with @ pricing posts to both systems."""
        item = LineItem(
            category="food",
            type="Plated Meal - 3 Courses",
            basis="per_person",
            pax=1174,
            unit_price=105.00,
            value=123270.00,
            money_type="contracted",
            posts_to="both",
        )
        assert item.category == "food"
        assert item.value == 123270.00
        assert item.needs_manual_value is False

    def test_cash_line_needs_manual_value(self):
        """A cash line (guest expense) needs manual value entry."""
        item = LineItem(
            category="beverage",
            type="Basic Spirits at Guest Expense",
            basis="guest_expense",
            value=0.0,
            money_type="cash",
            posts_to="delphi_only",
            needs_manual_value=True,
        )
        assert item.money_type == "cash"
        assert item.posts_to == "delphi_only"
        assert item.needs_manual_value is True

    def test_consumption_line_needs_manual_value(self):
        """A consumption line needs manual value entry."""
        item = LineItem(
            category="beverage",
            type="Speaker & VIP Drinks (Green Room)",
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )
        assert item.money_type == "consumption"
        assert item.posts_to == "both"
        assert item.needs_manual_value is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'recon.models'"

- [ ] **Step 3: Write models.py**

Create `recon/models.py`:
```python
"""Pydantic models for Event Order data."""

from datetime import date
from typing import Literal
from pydantic import BaseModel


class LineItem(BaseModel):
    """A single line item from an Event Order."""

    category: Literal["food", "beverage", "resource", "other", "venue_hire", "av"]
    type: str  # e.g. "Plated Meal - 3 Courses"
    basis: Literal[
        "per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense", "external"
    ]

    # Quantity fields (optional depending on basis)
    pax: int | None = None
    qty: int | None = None
    guards: int | None = None
    hours: float | None = None

    unit_price: float | None = None
    value: float  # Computed or manually entered

    money_type: Literal["contracted", "consumption", "cash", "external"]
    posts_to: Literal["both", "delphi_only", "none"]

    needs_manual_value: bool = False  # True for consumption/cash lines
    source: str | None = None  # "keyed_post_event", "pos", etc.


class EventOrder(BaseModel):
    """A complete Event Order (one BEO)."""

    pm_number: str
    beo_number: str
    event_name: str
    event_date: date | None = None
    line_items: list[LineItem] = []


class CategoryTotals(BaseModel):
    """Totals for a single category."""

    category: str
    delphi_total: float  # Includes cash
    opera_total: float  # Excludes cash


class WorksheetOutput(BaseModel):
    """Complete worksheet output with all totals."""

    event: EventOrder
    totals: list[CategoryTotals]
    delphi_grand_total: float
    opera_grand_total: float
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_models.py -v`
Expected: 3 passed

- [ ] **Step 5: Add EventOrder test**

Add to `tests/test_models.py`:
```python
class TestEventOrder:
    def test_event_order_with_line_items(self):
        """EventOrder holds metadata and line items."""
        event = EventOrder(
            pm_number="9353",
            beo_number="2895",
            event_name="Ultimate Origin Lunch 2026",
            event_date=date(2026, 6, 5),
            line_items=[
                LineItem(
                    category="food",
                    type="Plated Meal - 3 Courses",
                    basis="per_person",
                    pax=1174,
                    unit_price=105.00,
                    value=123270.00,
                    money_type="contracted",
                    posts_to="both",
                ),
            ],
        )
        assert event.pm_number == "9353"
        assert event.beo_number == "2895"
        assert len(event.line_items) == 1
        assert event.line_items[0].value == 123270.00
```

- [ ] **Step 6: Run all model tests**

Run: `pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 7: Commit**

```bash
git add recon/models.py tests/test_models.py
git commit -m "feat: add Pydantic models for LineItem, EventOrder, CategoryTotals"
```

---

## Task 3: Golden Test Fixture

**Files:**
- Create: `tests/fixtures/beo_2895.json`
- Create: `tests/test_builder_golden.py`

- [ ] **Step 1: Create golden fixture JSON**

Create `tests/fixtures/beo_2895.json`:
```json
{
  "pm_number": "9353",
  "beo_number": "2895",
  "event_name": "Ultimate Origin Lunch 2026",
  "event_date": "2026-06-05",
  "line_items": [
    {
      "category": "food",
      "type": "Plated Meal - 3 Courses",
      "basis": "per_person",
      "pax": 1174,
      "unit_price": 105.00,
      "value": 123270.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "food",
      "type": "AV Partners Crew Meals",
      "basis": "per_person",
      "pax": 4,
      "unit_price": 49.00,
      "value": 196.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "beverage",
      "type": "XXXX Cartons",
      "basis": "flat",
      "qty": 1,
      "unit_price": 2702.63,
      "value": 2702.63,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "beverage",
      "type": "Speaker & VIP Drinks (Green Room)",
      "basis": "consumption",
      "value": 326.00,
      "money_type": "consumption",
      "posts_to": "both",
      "source": "keyed_post_event"
    },
    {
      "category": "beverage",
      "type": "Classic Beverage Package - 4.5 Hours",
      "basis": "per_person",
      "pax": 1174,
      "unit_price": 63.00,
      "value": 73962.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "beverage",
      "type": "Basic Spirits at Guest Expense",
      "basis": "guest_expense",
      "value": 4848.97,
      "money_type": "cash",
      "posts_to": "delphi_only",
      "source": "pos"
    },
    {
      "category": "resource",
      "type": "Labour surcharge - XXXX Cartons",
      "basis": "flat",
      "value": 320.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "resource",
      "type": "Front of House Bar",
      "basis": "per_unit",
      "qty": 1,
      "unit_price": 530.00,
      "value": 530.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "resource",
      "type": "Red Carpet",
      "basis": "per_unit",
      "qty": 2,
      "unit_price": 150.00,
      "value": 300.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "other",
      "type": "Security - 8 guards 11:00-16:30",
      "basis": "hourly",
      "guards": 8,
      "hours": 5.5,
      "unit_price": 71.00,
      "value": 3124.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "venue_hire",
      "type": "Green Room Hire",
      "basis": "flat",
      "value": 500.00,
      "money_type": "contracted",
      "posts_to": "both"
    },
    {
      "category": "av",
      "type": "Audio Visual",
      "basis": "external",
      "value": 0.00,
      "money_type": "external",
      "posts_to": "none"
    }
  ]
}
```

- [ ] **Step 2: Write the golden test**

Create `tests/test_builder_golden.py`:
```python
"""Golden test: Builder must reproduce BEO 2895 totals exactly."""

import json
from pathlib import Path
import pytest
from recon.models import EventOrder
from recon.builder import compute_totals


@pytest.fixture
def beo_2895() -> EventOrder:
    """Load the golden fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "beo_2895.json"
    data = json.loads(fixture_path.read_text())
    return EventOrder.model_validate(data)


class TestGoldenBEO2895:
    """These targets come from the EO Reading Library spec."""

    def test_opera_grand_total(self, beo_2895: EventOrder):
        """Opera total must be exactly 205,230.63 (excludes cash)."""
        result = compute_totals(beo_2895)
        assert result.opera_grand_total == 205230.63

    def test_delphi_grand_total(self, beo_2895: EventOrder):
        """Delphi total must be exactly 210,079.60 (includes cash)."""
        result = compute_totals(beo_2895)
        assert result.delphi_grand_total == 210079.60

    def test_food_totals(self, beo_2895: EventOrder):
        """Food: 123,466.00 for both (no cash in food)."""
        result = compute_totals(beo_2895)
        food = next(t for t in result.totals if t.category == "food")
        assert food.delphi_total == 123466.00
        assert food.opera_total == 123466.00

    def test_beverage_totals(self, beo_2895: EventOrder):
        """Beverage: Delphi 81,839.60 (incl cash), Opera 76,990.63 (excl cash)."""
        result = compute_totals(beo_2895)
        bev = next(t for t in result.totals if t.category == "beverage")
        assert bev.delphi_total == 81839.60
        assert bev.opera_total == 76990.63

    def test_resource_totals(self, beo_2895: EventOrder):
        """Resource: 1,150.00 for both."""
        result = compute_totals(beo_2895)
        res = next(t for t in result.totals if t.category == "resource")
        assert res.delphi_total == 1150.00
        assert res.opera_total == 1150.00

    def test_other_totals(self, beo_2895: EventOrder):
        """Other (Security): 3,124.00 for both."""
        result = compute_totals(beo_2895)
        other = next(t for t in result.totals if t.category == "other")
        assert other.delphi_total == 3124.00
        assert other.opera_total == 3124.00

    def test_venue_hire_totals(self, beo_2895: EventOrder):
        """Venue Hire: 500.00 for both."""
        result = compute_totals(beo_2895)
        vh = next(t for t in result.totals if t.category == "venue_hire")
        assert vh.delphi_total == 500.00
        assert vh.opera_total == 500.00
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_builder_golden.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'recon.builder'"

- [ ] **Step 4: Commit fixture and test**

```bash
git add tests/fixtures/beo_2895.json tests/test_builder_golden.py
git commit -m "test: add golden test for BEO 2895 totals (red)"
```

---

## Task 4: Builder — Compute Totals

**Files:**
- Create: `recon/builder.py`

- [ ] **Step 1: Implement compute_totals**

Create `recon/builder.py`:
```python
"""Builder: compute category totals and generate worksheet."""

from collections import defaultdict
from recon.models import EventOrder, CategoryTotals, WorksheetOutput


def compute_totals(event: EventOrder) -> WorksheetOutput:
    """
    Compute Delphi and Opera totals from an EventOrder.

    - Delphi total = all lines (contracted + consumption + cash)
    - Opera total = exclude cash (only contracted + consumption)
    """
    # Group line items by category
    by_category: dict[str, list] = defaultdict(list)
    for item in event.line_items:
        by_category[item.category].append(item)

    totals = []
    for category, items in by_category.items():
        # Delphi = all lines
        delphi_total = sum(item.value for item in items)

        # Opera = exclude cash (money_type != "cash")
        opera_total = sum(
            item.value for item in items if item.money_type != "cash"
        )

        totals.append(
            CategoryTotals(
                category=category,
                delphi_total=round(delphi_total, 2),
                opera_total=round(opera_total, 2),
            )
        )

    # Sort totals by category for consistent output
    category_order = ["food", "beverage", "resource", "other", "venue_hire", "av"]
    totals.sort(key=lambda t: category_order.index(t.category) if t.category in category_order else 99)

    return WorksheetOutput(
        event=event,
        totals=totals,
        delphi_grand_total=round(sum(t.delphi_total for t in totals), 2),
        opera_grand_total=round(sum(t.opera_total for t in totals), 2),
    )
```

- [ ] **Step 2: Run golden tests to verify they pass**

Run: `pytest tests/test_builder_golden.py -v`
Expected: 7 passed

- [ ] **Step 3: Commit**

```bash
git add recon/builder.py
git commit -m "feat: implement compute_totals (golden tests pass)"
```

---

## Task 5: Builder — Excel Export

**Files:**
- Modify: `recon/builder.py`
- Create: `tests/test_builder_excel.py`

- [ ] **Step 1: Write test for Excel export**

Create `tests/test_builder_excel.py`:
```python
"""Tests for Excel worksheet generation."""

import json
from pathlib import Path
from io import BytesIO
import pytest
from openpyxl import load_workbook
from recon.models import EventOrder
from recon.builder import compute_totals, generate_excel


@pytest.fixture
def beo_2895() -> EventOrder:
    """Load the golden fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "beo_2895.json"
    data = json.loads(fixture_path.read_text())
    return EventOrder.model_validate(data)


class TestExcelExport:
    def test_generates_valid_excel(self, beo_2895: EventOrder):
        """generate_excel returns a valid Excel file."""
        worksheet_output = compute_totals(beo_2895)
        excel_bytes = generate_excel(worksheet_output)

        # Should be readable as Excel
        wb = load_workbook(BytesIO(excel_bytes))
        assert "Totals" in wb.sheetnames
        assert "Line Items" in wb.sheetnames

    def test_totals_sheet_has_correct_values(self, beo_2895: EventOrder):
        """Totals sheet contains the correct category totals."""
        worksheet_output = compute_totals(beo_2895)
        excel_bytes = generate_excel(worksheet_output)

        wb = load_workbook(BytesIO(excel_bytes))
        ws = wb["Totals"]

        # Header row
        assert ws["A1"].value == "Category"
        assert ws["B1"].value == "Delphi (incl cash)"
        assert ws["C1"].value == "Opera (excl cash)"

        # Find Food row and check values
        for row in range(2, ws.max_row + 1):
            if ws[f"A{row}"].value == "food":
                assert ws[f"B{row}"].value == 123466.00
                assert ws[f"C{row}"].value == 123466.00
                break

    def test_line_items_sheet_has_all_items(self, beo_2895: EventOrder):
        """Line Items sheet contains all line items."""
        worksheet_output = compute_totals(beo_2895)
        excel_bytes = generate_excel(worksheet_output)

        wb = load_workbook(BytesIO(excel_bytes))
        ws = wb["Line Items"]

        # Should have header + 12 line items
        assert ws.max_row == 13  # 1 header + 12 items
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_builder_excel.py -v`
Expected: FAIL with "cannot import name 'generate_excel'"

- [ ] **Step 3: Implement generate_excel**

Add to `recon/builder.py`:
```python
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment
from openpyxl.utils import get_column_letter


def generate_excel(output: WorksheetOutput) -> bytes:
    """
    Generate an Excel workbook from WorksheetOutput.

    Returns the workbook as bytes (ready for download).
    """
    wb = Workbook()

    # Sheet 1: Totals
    ws_totals = wb.active
    ws_totals.title = "Totals"

    # Header row
    headers = ["Category", "Delphi (incl cash)", "Opera (excl cash)"]
    for col, header in enumerate(headers, 1):
        cell = ws_totals.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    # Data rows
    for row_idx, total in enumerate(output.totals, 2):
        ws_totals.cell(row=row_idx, column=1, value=total.category)
        ws_totals.cell(row=row_idx, column=2, value=total.delphi_total)
        ws_totals.cell(row=row_idx, column=3, value=total.opera_total)

    # Grand total row
    grand_row = len(output.totals) + 2
    ws_totals.cell(row=grand_row, column=1, value="TOTAL").font = Font(bold=True)
    ws_totals.cell(row=grand_row, column=2, value=output.delphi_grand_total).font = Font(bold=True)
    ws_totals.cell(row=grand_row, column=3, value=output.opera_grand_total).font = Font(bold=True)

    # Column widths
    ws_totals.column_dimensions["A"].width = 15
    ws_totals.column_dimensions["B"].width = 20
    ws_totals.column_dimensions["C"].width = 20

    # Sheet 2: Line Items
    ws_items = wb.create_sheet("Line Items")

    item_headers = ["Category", "Type", "Basis", "Qty/Pax", "Unit Price", "Value", "Money Type", "Posts To"]
    for col, header in enumerate(item_headers, 1):
        cell = ws_items.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True)

    for row_idx, item in enumerate(output.event.line_items, 2):
        ws_items.cell(row=row_idx, column=1, value=item.category)
        ws_items.cell(row=row_idx, column=2, value=item.type)
        ws_items.cell(row=row_idx, column=3, value=item.basis)
        ws_items.cell(row=row_idx, column=4, value=item.pax or item.qty or item.guards or "")
        ws_items.cell(row=row_idx, column=5, value=item.unit_price or "")
        ws_items.cell(row=row_idx, column=6, value=item.value)
        ws_items.cell(row=row_idx, column=7, value=item.money_type)
        ws_items.cell(row=row_idx, column=8, value=item.posts_to)

    # Column widths for line items
    for col in range(1, 9):
        ws_items.column_dimensions[get_column_letter(col)].width = 18

    # Save to bytes
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_builder_excel.py -v`
Expected: 3 passed

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: All tests pass (10+ tests)

- [ ] **Step 6: Commit**

```bash
git add recon/builder.py tests/test_builder_excel.py
git commit -m "feat: add Excel export to builder"
```

---

## Task 6: PDF Parser — Header Extraction

**Files:**
- Create: `recon/parser.py`
- Create: `tests/test_parser.py`

- [ ] **Step 1: Write test for header extraction**

Create `tests/test_parser.py`:
```python
"""Tests for PDF parser."""

import pytest
from recon.parser import extract_headers


class TestHeaderExtraction:
    def test_extract_pm_number(self):
        """Extract Posting Master number from text."""
        text = "Some header text\nPosting Master #: 9353\nMore text"
        headers = extract_headers(text)
        assert headers["pm_number"] == "9353"

    def test_extract_beo_number(self):
        """Extract BEO number from text."""
        text = "Event info\nBEO#: 2895\nDetails"
        headers = extract_headers(text)
        assert headers["beo_number"] == "2895"

    def test_extract_event_name(self):
        """Extract event name from Post As line."""
        text = "Header\nPost As: Ultimate Origin Lunch 2026\nMore"
        headers = extract_headers(text)
        assert headers["event_name"] == "Ultimate Origin Lunch 2026"

    def test_extract_event_date(self):
        """Extract event date."""
        text = "Info\nEvent Date: Fri 05 Jun 2026\nDetails"
        headers = extract_headers(text)
        assert headers["event_date"] == "Fri 05 Jun 2026"

    def test_missing_fields_return_none(self):
        """Missing fields return None, not error."""
        text = "Some random text with no headers"
        headers = extract_headers(text)
        assert headers["pm_number"] is None
        assert headers["beo_number"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser.py::TestHeaderExtraction -v`
Expected: FAIL with "cannot import name 'extract_headers'"

- [ ] **Step 3: Implement extract_headers**

Create `recon/parser.py`:
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parser.py::TestHeaderExtraction -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add recon/parser.py tests/test_parser.py
git commit -m "feat: add header extraction to parser"
```

---

## Task 7: PDF Parser — Line Pattern Matching

**Files:**
- Modify: `recon/parser.py`
- Modify: `tests/test_parser.py`

- [ ] **Step 1: Write tests for line patterns**

Add to `tests/test_parser.py`:
```python
from recon.parser import extract_headers, parse_line, ParsedLine


class TestLineParsing:
    def test_per_person_pattern(self):
        """Parse '1174 Pax @ $105.00' pattern."""
        line = "Plated Meal – 3 Courses 1174 Pax @ $105.00 Per Person"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "per_person"
        assert result.pax == 1174
        assert result.unit_price == 105.00
        assert result.value == 123270.00

    def test_per_unit_pattern(self):
        """Parse '2 @ $150.00 Per 8m piece' pattern."""
        line = "Red Carpet 2 @ $150.00 Per 8m piece"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "per_unit"
        assert result.qty == 2
        assert result.unit_price == 150.00
        assert result.value == 300.00

    def test_flat_event_pattern(self):
        """Parse '@ $320.00 For This Event' pattern."""
        line = "Labour surcharge – XXXX Cartons @ $320.00 For This Event"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "flat"
        assert result.value == 320.00

    def test_flat_single_at_pattern(self):
        """Parse '1 @ $2,702.63' flat pattern."""
        line = "XXXX Cartons 1 @ $2,702.63"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "flat"
        assert result.qty == 1
        assert result.unit_price == 2702.63
        assert result.value == 2702.63

    def test_security_hourly_pattern(self):
        """Parse security guard hours pattern."""
        line = "8 Guards from 11:00 - 16:30 @ $71.00 Per Hour"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "hourly"
        assert result.guards == 8
        assert result.hours == 5.5
        assert result.unit_price == 71.00
        assert result.value == 3124.00

    def test_consumption_line(self):
        """Lines with 'on consumption' are flagged."""
        line = "Speaker & VIP Drinks (Green Room) on consumption"
        result = parse_line(line)
        assert result is not None
        assert result.money_type == "consumption"
        assert result.needs_manual_value is True
        assert result.value == 0.0

    def test_guest_expense_line(self):
        """Lines with 'at guest expense' are flagged as cash."""
        line = "Basic Spirits at guest expense"
        result = parse_line(line)
        assert result is not None
        assert result.money_type == "cash"
        assert result.posts_to == "delphi_only"
        assert result.needs_manual_value is True
        assert result.value == 0.0

    def test_unrecognized_line_returns_none(self):
        """Lines without recognized patterns return None."""
        line = "Some random text without pricing"
        result = parse_line(line)
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser.py::TestLineParsing -v`
Expected: FAIL with "cannot import name 'parse_line'"

- [ ] **Step 3: Add ParsedLine dataclass and parse_line function**

Add to `recon/parser.py`:
```python
from dataclasses import dataclass
from typing import Literal


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_parser.py::TestLineParsing -v`
Expected: 9 passed

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add recon/parser.py tests/test_parser.py
git commit -m "feat: add line pattern matching to parser"
```

---

## Task 8: PDF Parser — Full PDF Extraction

**Files:**
- Modify: `recon/parser.py`

- [ ] **Step 1: Add parse_pdf function**

Add to `recon/parser.py`:
```python
import pdfplumber
from pathlib import Path
from recon.models import LineItem, EventOrder
from datetime import datetime


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


def _detect_section(text: str) -> str | None:
    """Detect which section a line belongs to based on markers."""
    text_lower = text.lower()
    for marker, category in SECTION_MARKERS.items():
        if marker in text_lower:
            return category
    return None


def parse_pdf(pdf_path: str | Path) -> EventOrder:
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
    line_items: list[LineItem] = []
    current_section: str | None = None

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
```

- [ ] **Step 2: Update imports at top of parser.py**

Ensure `recon/parser.py` has these imports at the top:
```python
"""PDF Parser: extract Event Order data from PDF text."""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import pdfplumber

from recon.models import LineItem, EventOrder
```

- [ ] **Step 3: Run all tests to ensure nothing broke**

Run: `pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add recon/parser.py
git commit -m "feat: add full PDF extraction with section detection"
```

---

## Task 9: Delphi Adapter

**Files:**
- Create: `recon/delphi_adapter.py`
- Create: `tests/test_delphi_adapter.py`

- [ ] **Step 1: Write test for Delphi Excel parsing**

Create `tests/test_delphi_adapter.py`:
```python
"""Tests for Delphi posting report adapter."""

from io import BytesIO
import pytest
from openpyxl import Workbook
from recon.delphi_adapter import parse_delphi_report


def create_sample_delphi_excel() -> bytes:
    """Create a sample Delphi export for testing."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Posting Report"

    # Header row
    ws["A1"] = "Category"
    ws["B1"] = "Amount"

    # Data rows
    data = [
        ("Food", 123466.00),
        ("Beverage", 81839.60),
        ("Resource", 1150.00),
        ("Other", 3124.00),
        ("Venue Hire", 500.00),
    ]
    for row_idx, (category, amount) in enumerate(data, 2):
        ws[f"A{row_idx}"] = category
        ws[f"B{row_idx}"] = amount

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer.read()


class TestDelphiAdapter:
    def test_parse_delphi_report(self):
        """Parse Delphi Excel and extract category totals."""
        excel_bytes = create_sample_delphi_excel()
        result = parse_delphi_report(BytesIO(excel_bytes))

        assert result["food"] == 123466.00
        assert result["beverage"] == 81839.60
        assert result["resource"] == 1150.00
        assert result["other"] == 3124.00
        assert result["venue_hire"] == 500.00

    def test_normalizes_category_names(self):
        """Category names are normalized to lowercase with underscores."""
        excel_bytes = create_sample_delphi_excel()
        result = parse_delphi_report(BytesIO(excel_bytes))

        # "Venue Hire" should become "venue_hire"
        assert "venue_hire" in result
        assert "Venue Hire" not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_delphi_adapter.py -v`
Expected: FAIL with "cannot import name 'parse_delphi_report'"

- [ ] **Step 3: Implement delphi_adapter.py**

Create `recon/delphi_adapter.py`:
```python
"""Adapter for parsing Delphi posting reports."""

from io import BytesIO
from typing import BinaryIO
from openpyxl import load_workbook


# Mapping from Delphi category names to our normalized names
CATEGORY_MAPPING = {
    "food": "food",
    "beverage": "beverage",
    "resource": "resource",
    "other": "other",
    "venue hire": "venue_hire",
    "venue_hire": "venue_hire",
    "av": "av",
    "audio visual": "av",
}


def _normalize_category(name: str) -> str:
    """Normalize a category name to our standard format."""
    normalized = name.lower().strip()
    return CATEGORY_MAPPING.get(normalized, normalized.replace(" ", "_"))


def parse_delphi_report(file: BinaryIO) -> dict[str, float]:
    """
    Parse a Delphi posting report Excel file.

    Expects columns: Category, Amount (or similar).
    Returns dict mapping normalized category names to amounts.
    """
    wb = load_workbook(file, data_only=True)
    ws = wb.active

    # Find the header row and identify columns
    category_col = None
    amount_col = None

    for col in range(1, ws.max_column + 1):
        header = str(ws.cell(row=1, column=col).value or "").lower()
        if "category" in header or "account" in header:
            category_col = col
        elif "amount" in header or "total" in header:
            amount_col = col

    if category_col is None or amount_col is None:
        raise ValueError("Could not find Category and Amount columns in Delphi report")

    # Parse data rows
    result: dict[str, float] = {}
    for row in range(2, ws.max_row + 1):
        category_cell = ws.cell(row=row, column=category_col).value
        amount_cell = ws.cell(row=row, column=amount_col).value

        if category_cell is None:
            continue

        category = _normalize_category(str(category_cell))
        amount = float(amount_cell) if amount_cell is not None else 0.0

        # Accumulate in case there are multiple rows per category
        result[category] = result.get(category, 0.0) + amount

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_delphi_adapter.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add recon/delphi_adapter.py tests/test_delphi_adapter.py
git commit -m "feat: add Delphi posting report adapter"
```

---

## Task 10: Reconciler

**Files:**
- Create: `recon/reconciler.py`
- Create: `tests/test_reconciler.py`

- [ ] **Step 1: Write test for reconciliation**

Create `tests/test_reconciler.py`:
```python
"""Tests for reconciler."""

import pytest
from recon.models import CategoryTotals, WorksheetOutput, EventOrder
from recon.reconciler import reconcile, Discrepancy


@pytest.fixture
def sample_worksheet() -> WorksheetOutput:
    """Create a sample worksheet output."""
    return WorksheetOutput(
        event=EventOrder(
            pm_number="9353",
            beo_number="2895",
            event_name="Test Event",
            line_items=[],
        ),
        totals=[
            CategoryTotals(category="food", delphi_total=123466.00, opera_total=123466.00),
            CategoryTotals(category="beverage", delphi_total=81839.60, opera_total=76990.63),
            CategoryTotals(category="resource", delphi_total=1150.00, opera_total=1150.00),
        ],
        delphi_grand_total=206455.60,
        opera_grand_total=201606.63,
    )


class TestReconciler:
    def test_no_discrepancies_when_matching(self, sample_worksheet: WorksheetOutput):
        """No discrepancies when Delphi report matches exactly."""
        delphi_report = {
            "food": 123466.00,
            "beverage": 81839.60,
            "resource": 1150.00,
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 0

    def test_rounding_tolerance(self, sample_worksheet: WorksheetOutput):
        """Variances within 5 cents are ignored."""
        delphi_report = {
            "food": 123466.03,  # 3 cents off
            "beverage": 81839.60,
            "resource": 1150.00,
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 0

    def test_detects_variance(self, sample_worksheet: WorksheetOutput):
        """Detects variance above tolerance."""
        delphi_report = {
            "food": 123466.00,
            "beverage": 81839.60,
            "resource": 1000.00,  # 150 off
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 1
        assert discrepancies[0].category == "resource"
        assert discrepancies[0].expected == 1150.00
        assert discrepancies[0].posted == 1000.00
        assert discrepancies[0].variance == -150.00

    def test_missing_category_in_delphi(self, sample_worksheet: WorksheetOutput):
        """Detects category missing from Delphi report."""
        delphi_report = {
            "food": 123466.00,
            "beverage": 81839.60,
            # resource missing
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 1
        assert discrepancies[0].category == "resource"
        assert discrepancies[0].posted == 0.0
        assert "not posted" in discrepancies[0].likely_cause.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_reconciler.py -v`
Expected: FAIL with "cannot import name 'reconcile'"

- [ ] **Step 3: Implement reconciler.py**

Create `recon/reconciler.py`:
```python
"""Reconciler: compare worksheet vs Delphi posting report."""

from dataclasses import dataclass
from recon.models import WorksheetOutput


ROUNDING_TOLERANCE = 0.05  # 5 cents


@dataclass
class Discrepancy:
    """A discrepancy between expected and posted values."""

    category: str
    expected: float
    posted: float
    variance: float
    likely_cause: str


def _diagnose_cause(
    category: str,
    expected: float,
    posted: float,
    variance: float,
    worksheet: WorksheetOutput,
) -> str:
    """
    Determine the likely cause of a discrepancy.

    Uses heuristics from the EO Reading Library spec.
    """
    abs_variance = abs(variance)

    # Check if variance matches a cash line value
    for item in worksheet.event.line_items:
        if item.money_type == "cash" and abs(abs_variance - item.value) < 1.0:
            return f"Cash sale ({item.type}) likely posted to Opera by mistake, or excluded from Delphi"

    # Check if variance matches a consumption line value
    for item in worksheet.event.line_items:
        if item.money_type == "consumption" and abs(abs_variance - item.value) < 1.0:
            return f"Consumption ({item.type}) not keyed, or keyed to wrong category"

    # Check for GST mismatch (variance ≈ 10% or 1/11 of expected)
    if expected > 0:
        ratio = abs_variance / expected
        if 0.09 < ratio < 0.11:
            return "GST treatment mismatch (inc vs ex GST)"
        if 0.085 < ratio < 0.095:  # 1/11 ≈ 0.0909
            return "GST treatment mismatch (inc vs ex GST)"

    # Check if variance equals a specific line's value
    for item in worksheet.event.line_items:
        if item.category == category and abs(abs_variance - item.value) < 1.0:
            return f"Line '{item.type}' appears not to have been posted"

    # Category missing entirely
    if posted == 0.0 and expected > 0:
        return f"Entire {category} category not posted"

    # Default
    return "Variance detected - manual review required"


def reconcile(
    worksheet: WorksheetOutput,
    delphi_report: dict[str, float],
) -> list[Discrepancy]:
    """
    Compare computed worksheet against Delphi posting report.

    Returns list of discrepancies (empty if all match within tolerance).
    """
    discrepancies: list[Discrepancy] = []

    for total in worksheet.totals:
        expected = total.delphi_total
        posted = delphi_report.get(total.category, 0.0)
        variance = posted - expected

        # Skip if within rounding tolerance
        if abs(variance) <= ROUNDING_TOLERANCE:
            continue

        cause = _diagnose_cause(
            category=total.category,
            expected=expected,
            posted=posted,
            variance=variance,
            worksheet=worksheet,
        )

        discrepancies.append(
            Discrepancy(
                category=total.category,
                expected=expected,
                posted=posted,
                variance=round(variance, 2),
                likely_cause=cause,
            )
        )

    return discrepancies
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reconciler.py -v`
Expected: 4 passed

- [ ] **Step 5: Run all tests**

Run: `pytest -v`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add recon/reconciler.py tests/test_reconciler.py
git commit -m "feat: add reconciler with diagnostic heuristics"
```

---

## Task 11: Streamlit App — Basic Structure

**Files:**
- Create: `app.py`
- Create: `.streamlit/secrets.toml.example`

- [ ] **Step 1: Create secrets template**

Create `.streamlit/secrets.toml.example`:
```toml
# Copy this to secrets.toml and set your password
# DO NOT commit secrets.toml to git

password = "your-team-password-here"
```

- [ ] **Step 2: Add .gitignore**

Create `.gitignore`:
```
# Python
__pycache__/
*.py[cod]
*$py.class
.Python
venv/
.venv/
*.egg-info/

# Streamlit
.streamlit/secrets.toml

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
```

- [ ] **Step 3: Create app.py with authentication and step structure**

Create `app.py`:
```python
"""Event Order Reconciliation Tool — Streamlit App."""

import streamlit as st

# Page config
st.set_page_config(
    page_title="EO Reconciliation Tool",
    page_icon="📊",
    layout="wide",
)


def check_password() -> bool:
    """Simple password authentication."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        return True

    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if password == st.secrets.get("password", ""):
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password")
    return False


def main():
    st.title("📊 Event Order Reconciliation Tool")

    # Authentication
    if not check_password():
        st.stop()

    # Initialize session state
    if "step" not in st.session_state:
        st.session_state.step = 1
    if "event_order" not in st.session_state:
        st.session_state.event_order = None
    if "worksheet_output" not in st.session_state:
        st.session_state.worksheet_output = None

    # Progress indicator
    steps = ["1. Upload & Extract", "2. Complete Values", "3. Generate Worksheet", "4. Reconcile"]
    cols = st.columns(4)
    for i, (col, step_name) in enumerate(zip(cols, steps), 1):
        if i < st.session_state.step:
            col.success(step_name)
        elif i == st.session_state.step:
            col.info(step_name)
        else:
            col.empty()
            col.write(step_name)

    st.divider()

    # Render current step
    if st.session_state.step == 1:
        render_step_1_upload()
    elif st.session_state.step == 2:
        render_step_2_values()
    elif st.session_state.step == 3:
        render_step_3_generate()
    elif st.session_state.step == 4:
        render_step_4_reconcile()


def render_step_1_upload():
    """Step 1: Upload EO PDF and extract data."""
    st.header("Step 1: Upload & Extract")
    st.write("Upload an Event Order PDF to extract line items.")

    # Placeholder - will implement in next task
    st.info("PDF upload will be implemented in the next step.")

    if st.button("Skip to Step 2 (for testing)"):
        st.session_state.step = 2
        st.rerun()


def render_step_2_values():
    """Step 2: Enter consumption/cash values."""
    st.header("Step 2: Complete Values")
    st.write("Enter values for consumption and cash lines.")

    # Placeholder
    st.info("Value entry will be implemented in the next step.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 1
            st.rerun()
    with col2:
        if st.button("Next →"):
            st.session_state.step = 3
            st.rerun()


def render_step_3_generate():
    """Step 3: Generate worksheet and download."""
    st.header("Step 3: Generate Worksheet")
    st.write("Review totals and download the worksheet.")

    # Placeholder
    st.info("Worksheet generation will be implemented in the next step.")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("Next →"):
            st.session_state.step = 4
            st.rerun()


def render_step_4_reconcile():
    """Step 4: Upload Delphi report and reconcile."""
    st.header("Step 4: Reconcile")
    st.write("Upload Delphi posting report and compare.")

    # Placeholder
    st.info("Reconciliation will be implemented in the next step.")

    if st.button("← Back"):
        st.session_state.step = 3
        st.rerun()

    if st.button("Start Over"):
        for key in list(st.session_state.keys()):
            if key != "authenticated":
                del st.session_state[key]
        st.rerun()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Test the app locally**

Run:
```bash
cd /Users/zakedrich/Documents/work/coding/auto_posting
source venv/bin/activate
echo 'password = "test"' > .streamlit/secrets.toml
streamlit run app.py
```

Expected: App opens in browser, shows login, accepts "test" password, shows 4-step wizard

- [ ] **Step 5: Commit**

```bash
git add app.py .streamlit/secrets.toml.example .gitignore
git commit -m "feat: add Streamlit app skeleton with auth and step navigation"
```

---

## Task 12: Streamlit App — Step 1 (Upload & Extract)

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Implement Step 1 with PDF upload and extraction**

Replace `render_step_1_upload` in `app.py`:
```python
def render_step_1_upload():
    """Step 1: Upload EO PDF and extract data."""
    st.header("Step 1: Upload & Extract")
    st.write("Upload an Event Order PDF to extract line items.")

    uploaded_file = st.file_uploader("Choose an EO PDF", type=["pdf"])

    if uploaded_file is not None:
        if st.button("Extract"):
            with st.spinner("Extracting..."):
                # Save to temp file for pdfplumber
                import tempfile
                from recon.parser import parse_pdf

                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                try:
                    event_order = parse_pdf(tmp_path)
                    st.session_state.event_order = event_order
                    st.success(f"Extracted {len(event_order.line_items)} line items")
                except Exception as e:
                    st.error(f"Error extracting PDF: {e}")
                    return
                finally:
                    import os
                    os.unlink(tmp_path)

    # Show extracted data if available
    if st.session_state.event_order is not None:
        event = st.session_state.event_order
        st.subheader("Event Details")
        col1, col2, col3 = st.columns(3)
        col1.metric("PM#", event.pm_number or "—")
        col2.metric("BEO#", event.beo_number or "—")
        col3.metric("Event", event.event_name or "—")

        st.subheader("Line Items")

        # Convert to dataframe for editing
        import pandas as pd

        items_data = []
        for i, item in enumerate(event.line_items):
            items_data.append({
                "idx": i,
                "Category": item.category,
                "Type": item.type,
                "Basis": item.basis,
                "Qty/Pax": item.pax or item.qty or item.guards or "",
                "Unit Price": item.unit_price or "",
                "Value": item.value,
                "Money Type": item.money_type,
                "Needs Value": "⚠️" if item.needs_manual_value else "✓",
            })

        df = pd.DataFrame(items_data)

        # Highlight rows needing manual values
        st.dataframe(
            df.drop(columns=["idx"]),
            use_container_width=True,
            hide_index=True,
        )

        # Count items needing values
        needs_values = sum(1 for item in event.line_items if item.needs_manual_value)
        if needs_values > 0:
            st.warning(f"{needs_values} line(s) need manual values (consumption/cash)")

        if st.button("Confirm Extraction →"):
            st.session_state.step = 2
            st.rerun()
```

- [ ] **Step 2: Add imports at top of app.py**

Ensure these imports are at the top of `app.py`:
```python
"""Event Order Reconciliation Tool — Streamlit App."""

import os
import tempfile

import pandas as pd
import streamlit as st

from recon.parser import parse_pdf
from recon.builder import compute_totals, generate_excel
from recon.delphi_adapter import parse_delphi_report
from recon.reconciler import reconcile
```

- [ ] **Step 3: Test Step 1 locally**

Run: `streamlit run app.py`
Expected: Can upload PDF, see extracted data, proceed to Step 2

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: implement Step 1 PDF upload and extraction"
```

---

## Task 13: Streamlit App — Step 2 (Complete Values)

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Implement Step 2 with value entry**

Replace `render_step_2_values` in `app.py`:
```python
def render_step_2_values():
    """Step 2: Enter consumption/cash values."""
    st.header("Step 2: Complete Values")

    if st.session_state.event_order is None:
        st.error("No event order loaded. Go back to Step 1.")
        if st.button("← Back to Step 1"):
            st.session_state.step = 1
            st.rerun()
        return

    event = st.session_state.event_order

    # Find items needing manual values
    needs_values = [
        (i, item) for i, item in enumerate(event.line_items)
        if item.needs_manual_value
    ]

    if not needs_values:
        st.success("All line items have values. Proceeding to next step.")
        st.session_state.step = 3
        st.rerun()
        return

    st.write(f"Enter values for {len(needs_values)} line(s):")

    # Create input fields for each item needing a value
    updated = False
    for idx, item in needs_values:
        col1, col2, col3 = st.columns([2, 1, 1])
        with col1:
            st.write(f"**{item.type}**")
            st.caption(f"Category: {item.category} | Type: {item.money_type}")
        with col2:
            source = "POS" if item.money_type == "cash" else "Post-event"
            st.caption(f"Source: {source}")
        with col3:
            new_value = st.number_input(
                "Value ($)",
                min_value=0.0,
                value=item.value,
                step=0.01,
                key=f"value_{idx}",
                format="%.2f",
            )
            if new_value != item.value:
                event.line_items[idx].value = new_value
                updated = True

    if updated:
        st.session_state.event_order = event

    # Show running totals
    st.divider()
    st.subheader("Running Totals")

    from recon.builder import compute_totals
    preview = compute_totals(event)

    col1, col2 = st.columns(2)
    col1.metric("Delphi Total", f"${preview.delphi_grand_total:,.2f}")
    col2.metric("Opera Total", f"${preview.opera_grand_total:,.2f}")

    st.divider()

    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 1
            st.rerun()
    with col2:
        # Check if all values are filled
        all_filled = all(item.value > 0 for _, item in needs_values)
        if all_filled:
            if st.button("Values Complete →"):
                st.session_state.step = 3
                st.rerun()
        else:
            st.button("Values Complete →", disabled=True)
            st.caption("Enter all values to continue")
```

- [ ] **Step 2: Test Step 2 locally**

Run: `streamlit run app.py`
Expected: Can enter values for consumption/cash lines, see running totals, proceed to Step 3

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: implement Step 2 value entry for consumption/cash lines"
```

---

## Task 14: Streamlit App — Step 3 (Generate Worksheet)

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Implement Step 3 with totals display and download**

Replace `render_step_3_generate` in `app.py`:
```python
def render_step_3_generate():
    """Step 3: Generate worksheet and download."""
    st.header("Step 3: Generate Worksheet")

    if st.session_state.event_order is None:
        st.error("No event order loaded. Go back to Step 1.")
        if st.button("← Back to Step 1"):
            st.session_state.step = 1
            st.rerun()
        return

    event = st.session_state.event_order

    # Compute totals
    from recon.builder import compute_totals, generate_excel

    worksheet_output = compute_totals(event)
    st.session_state.worksheet_output = worksheet_output

    # Event info
    st.subheader("Event")
    st.write(f"**{event.event_name}** | PM# {event.pm_number} | BEO# {event.beo_number}")
    if event.event_date:
        st.write(f"Date: {event.event_date}")

    # Category totals table
    st.subheader("Category Totals")

    totals_data = []
    for total in worksheet_output.totals:
        totals_data.append({
            "Category": total.category.replace("_", " ").title(),
            "Delphi (incl cash)": f"${total.delphi_total:,.2f}",
            "Opera (excl cash)": f"${total.opera_total:,.2f}",
        })

    totals_data.append({
        "Category": "**TOTAL**",
        "Delphi (incl cash)": f"**${worksheet_output.delphi_grand_total:,.2f}**",
        "Opera (excl cash)": f"**${worksheet_output.opera_grand_total:,.2f}**",
    })

    st.table(pd.DataFrame(totals_data))

    # Grand totals prominently
    col1, col2 = st.columns(2)
    col1.metric("Delphi Grand Total", f"${worksheet_output.delphi_grand_total:,.2f}")
    col2.metric("Opera Grand Total", f"${worksheet_output.opera_grand_total:,.2f}")

    # Download button
    st.divider()
    excel_bytes = generate_excel(worksheet_output)

    filename = f"worksheet_{event.beo_number or 'export'}.xlsx"
    st.download_button(
        label="📥 Download Worksheet (.xlsx)",
        data=excel_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.divider()

    # Navigation
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 2
            st.rerun()
    with col2:
        if st.button("Proceed to Reconciliation →"):
            st.session_state.step = 4
            st.rerun()
    with col3:
        if st.button("✓ Done (Skip Reconciliation)"):
            st.balloons()
            st.success("Worksheet generated successfully!")
```

- [ ] **Step 2: Test Step 3 locally**

Run: `streamlit run app.py`
Expected: See totals table, download worksheet, proceed to Step 4 or finish

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: implement Step 3 worksheet generation and download"
```

---

## Task 15: Streamlit App — Step 4 (Reconcile)

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Implement Step 4 with Delphi upload and reconciliation**

Replace `render_step_4_reconcile` in `app.py`:
```python
def render_step_4_reconcile():
    """Step 4: Upload Delphi report and reconcile."""
    st.header("Step 4: Reconcile")

    if st.session_state.worksheet_output is None:
        st.error("No worksheet generated. Go back to Step 3.")
        if st.button("← Back to Step 3"):
            st.session_state.step = 3
            st.rerun()
        return

    worksheet = st.session_state.worksheet_output

    st.write("Upload the Delphi posting report to compare against computed totals.")

    uploaded_file = st.file_uploader("Choose Delphi Report (.xlsx)", type=["xlsx"])

    if uploaded_file is not None:
        if st.button("Reconcile"):
            with st.spinner("Reconciling..."):
                from io import BytesIO
                from recon.delphi_adapter import parse_delphi_report
                from recon.reconciler import reconcile

                try:
                    delphi_report = parse_delphi_report(BytesIO(uploaded_file.read()))
                    discrepancies = reconcile(worksheet, delphi_report)
                    st.session_state.discrepancies = discrepancies
                    st.session_state.delphi_report = delphi_report
                except Exception as e:
                    st.error(f"Error parsing Delphi report: {e}")
                    return

    # Show results if available
    if "discrepancies" in st.session_state:
        discrepancies = st.session_state.discrepancies
        delphi_report = st.session_state.delphi_report

        st.divider()
        st.subheader("Reconciliation Results")

        if not discrepancies:
            st.success("✅ All categories match within tolerance!")
        else:
            st.warning(f"⚠️ {len(discrepancies)} discrepancy/ies found")

        # Build comparison table
        comparison_data = []
        for total in worksheet.totals:
            posted = delphi_report.get(total.category, 0.0)
            variance = posted - total.delphi_total

            # Determine status
            if abs(variance) <= 0.05:
                status = "✅ Match"
                cause = "—"
            else:
                status = "❌ Variance"
                disc = next((d for d in discrepancies if d.category == total.category), None)
                cause = disc.likely_cause if disc else "Unknown"

            comparison_data.append({
                "Category": total.category.replace("_", " ").title(),
                "Expected": f"${total.delphi_total:,.2f}",
                "Posted": f"${posted:,.2f}",
                "Variance": f"${variance:,.2f}",
                "Status": status,
                "Likely Cause": cause,
            })

        st.table(pd.DataFrame(comparison_data))

        # Discrepancy details
        if discrepancies:
            st.subheader("Discrepancy Details")
            for disc in discrepancies:
                with st.expander(f"🔴 {disc.category.replace('_', ' ').title()}: ${abs(disc.variance):,.2f} variance"):
                    st.write(f"**Expected:** ${disc.expected:,.2f}")
                    st.write(f"**Posted:** ${disc.posted:,.2f}")
                    st.write(f"**Variance:** ${disc.variance:,.2f}")
                    st.write(f"**Likely Cause:** {disc.likely_cause}")

    st.divider()

    # Navigation
    col1, col2 = st.columns(2)
    with col1:
        if st.button("← Back"):
            st.session_state.step = 3
            st.rerun()
    with col2:
        if st.button("🔄 Start Over"):
            for key in list(st.session_state.keys()):
                if key != "authenticated":
                    del st.session_state[key]
            st.rerun()
```

- [ ] **Step 2: Test Step 4 locally**

Run: `streamlit run app.py`
Expected: Can upload Delphi report, see comparison table, see discrepancy details

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: implement Step 4 reconciliation with discrepancy diagnostics"
```

---

## Task 16: README and Final Polish

**Files:**
- Create: `README.md`
- Update: `recon/__init__.py`

- [ ] **Step 1: Create README**

Create `README.md`:
```markdown
# Event Order Reconciliation Tool

A Streamlit web app for The Star Brisbane that automates the sales-posting workflow:

1. **Extract** line items from Event Order (EO) PDFs
2. **Enter** consumption and cash values
3. **Generate** reconciliation worksheets
4. **Reconcile** against Delphi posting reports

## Quick Start

### Local Development

```bash
# Clone the repo
git clone <your-repo-url>
cd event-recon

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Set up secrets
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml and set your password

# Run the app
streamlit run app.py
```

### Run Tests

```bash
pytest -v
```

## Deployment (Streamlit Community Cloud)

1. Push to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io)
3. Connect your GitHub repo
4. Set secrets in the Streamlit Cloud dashboard:
   - `password = "your-team-password"`
5. Deploy

## Project Structure

```
event-recon/
├── app.py                  # Streamlit app entry point
├── recon/
│   ├── models.py           # Pydantic data models
│   ├── parser.py           # PDF extraction
│   ├── builder.py          # Totals computation + Excel export
│   ├── reconciler.py       # Discrepancy detection
│   └── delphi_adapter.py   # Delphi report parsing
├── tests/                  # Test suite
└── docs/                   # Design specs and plans
```

## How It Works

### The Three Money Types

| Type | Trigger Phrase | Posts to Opera? |
|------|----------------|-----------------|
| Contracted | `@ $X` pricing | Yes |
| Consumption | "on consumption" | Yes |
| Cash | "at guest expense" | **No** |

**Delphi** includes all revenue. **Opera** excludes cash sales.

### Golden Test

The tool must reproduce the BEO 2895 example:
- Opera Total: **$205,230.63**
- Delphi Total: **$210,079.60**

The $4,848.97 difference is exactly the cash sale.

## License

Internal use only — The Star Brisbane
```

- [ ] **Step 2: Update recon/__init__.py with exports**

Update `recon/__init__.py`:
```python
"""Event Order Reconciliation Tool."""

from recon.models import LineItem, EventOrder, CategoryTotals, WorksheetOutput
from recon.parser import parse_pdf, parse_line, extract_headers
from recon.builder import compute_totals, generate_excel
from recon.reconciler import reconcile, Discrepancy
from recon.delphi_adapter import parse_delphi_report

__all__ = [
    "LineItem",
    "EventOrder",
    "CategoryTotals",
    "WorksheetOutput",
    "parse_pdf",
    "parse_line",
    "extract_headers",
    "compute_totals",
    "generate_excel",
    "reconcile",
    "Discrepancy",
    "parse_delphi_report",
]
```

- [ ] **Step 3: Run all tests one final time**

Run: `pytest -v`
Expected: All tests pass

- [ ] **Step 4: Commit**

```bash
git add README.md recon/__init__.py
git commit -m "docs: add README and update package exports"
```

---

## Task 17: Push to GitHub

**Files:** None (git operations only)

- [ ] **Step 1: Create GitHub repository**

Go to github.com and create a new repository named `event-recon` (or your preferred name).

- [ ] **Step 2: Add remote and push**

Run:
```bash
git remote add origin https://github.com/<your-username>/event-recon.git
git branch -M main
git push -u origin main
```

- [ ] **Step 3: Verify repository**

Go to your GitHub repo URL and verify all files are present.

---

## Summary

After completing all tasks, you will have:

1. **Core library** (`recon/`) with:
   - Pydantic models for EO data
   - PDF parser with pattern matching
   - Builder for totals + Excel export
   - Reconciler with diagnostic heuristics
   - Delphi adapter for report parsing

2. **Test suite** (`tests/`) with:
   - Golden test (BEO 2895: 205,230.63 / 210,079.60)
   - Unit tests for all components

3. **Streamlit app** (`app.py`) with:
   - Password authentication
   - 4-step wizard flow
   - PDF upload and extraction
   - Manual value entry
   - Worksheet download
   - Reconciliation with discrepancy display

4. **Ready for deployment** to Streamlit Community Cloud
