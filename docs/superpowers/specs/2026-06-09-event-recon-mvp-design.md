# Event Order Reconciliation Tool — MVP Design

**Date:** 2026-06-09
**Owner:** Zak
**Status:** Approved

## Overview

A Streamlit web app that automates the sales-posting workflow for The Star Brisbane events. The tool reads Event Order (EO) PDFs, extracts line items, computes category totals for Delphi and Opera, generates a worksheet, and reconciles against Delphi posting reports.

## Scope

**In scope for MVP:**
- Full pipeline: PDF extraction → human review → worksheet generation → reconciliation
- Deterministic parsing (no LLM)
- Manual entry for consumption and cash values
- Delphi import via Excel upload
- Simple category totals output
- Streamlit Community Cloud deployment with password auth
- Team of 5+ daily users

**Out of scope for MVP:**
- LLM-assisted extraction (future enhancement)
- Persistent storage / audit logs
- API integration with Delphi
- DDP package splits (placeholder in specs)
- Minimum-spend waterfall automation (operator-confirmed)

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit App                           │
├─────────────────────────────────────────────────────────────┤
│  Step 1: Upload & Extract                                   │
│  ┌─────────┐    ┌──────────┐    ┌─────────────────┐        │
│  │ EO PDF  │───▶│ Parser   │───▶│ Editable Table  │        │
│  └─────────┘    └──────────┘    └─────────────────┘        │
├─────────────────────────────────────────────────────────────┤
│  Step 2: Complete Values                                    │
│  ┌─────────────────────────────────────────────────┐       │
│  │ Consumption/cash lines → manual value entry     │       │
│  └─────────────────────────────────────────────────┘       │
├─────────────────────────────────────────────────────────────┤
│  Step 3: Generate Worksheet                                 │
│  ┌──────────┐    ┌─────────────┐    ┌──────────────┐       │
│  │ Compute  │───▶│ Totals Grid │───▶│ Download .xlsx│      │
│  └──────────┘    └─────────────┘    └──────────────┘       │
├─────────────────────────────────────────────────────────────┤
│  Step 4: Reconcile                                          │
│  ┌──────────────┐    ┌────────────┐    ┌────────────────┐  │
│  │ Delphi Excel │───▶│ Reconciler │───▶│ Discrepancies  │  │
│  └──────────────┘    └────────────┘    └────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Core modules:**
- `app.py` — Streamlit entry point, wizard flow
- `recon/models.py` — Pydantic schemas
- `recon/parser.py` — PDF extraction + pattern matching
- `recon/builder.py` — Compute totals, generate Excel
- `recon/reconciler.py` — Compare vs Delphi, diagnostics
- `recon/delphi_adapter.py` — Delphi Excel ingestion

## Data Model

```python
class LineItem(BaseModel):
    category: Literal["food", "beverage", "resource", "other", "venue_hire", "av"]
    type: str                          # e.g. "Plated Meal - 3 Courses"
    basis: Literal["per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense", "external"]

    # Quantity fields (optional depending on basis)
    pax: int | None = None
    qty: int | None = None
    guards: int | None = None
    hours: float | None = None

    unit_price: float | None = None
    value: float                       # Computed or manually entered

    money_type: Literal["contracted", "consumption", "cash", "external"]
    posts_to: Literal["both", "delphi_only", "none"]

    needs_manual_value: bool = False   # True for consumption/cash lines
    source: str | None = None          # "keyed_post_event", "pos", etc.

class EventOrder(BaseModel):
    pm_number: str
    beo_number: str
    event_name: str
    event_date: date | None
    line_items: list[LineItem]

class CategoryTotals(BaseModel):
    category: str
    delphi_total: float    # Includes cash
    opera_total: float     # Excludes cash

class WorksheetOutput(BaseModel):
    event: EventOrder
    totals: list[CategoryTotals]
    delphi_grand_total: float
    opera_grand_total: float
```

**Key decisions:**
- `money_type` drives posting: "contracted" and "consumption" → both systems; "cash" → Delphi only
- `needs_manual_value` flags lines where operator must enter the actual figure
- `posts_to` is derived from `money_type` but stored explicitly for clarity

## PDF Parser

Deterministic pattern matching using pdfplumber.

**Header extraction (regex):**
- `Posting Master #: (\d+)` → pm_number
- `BEO#: (\d+)` → beo_number
- `Post As: (.+)` → event_name
- `Event Date: (.+)` → event_date

**Section detection (anchor phrases):**
- "Menu Content" → food
- "Beverage Selection" → beverage
- "Additional Resources" → resource
- "Security" → other
- "Venue Hire" / "Minimum Spend" → venue_hire
- "Audio Visual" → av

**Line parsing patterns:**

| Pattern | Example | Extraction |
|---------|---------|------------|
| `(\d+)\s*Pax\s*@\s*\$?([\d,]+\.?\d*)` | "1174 Pax @ $105.00" | pax=1174, unit_price=105, basis=per_person |
| `(\d+)\s*@\s*\$?([\d,]+\.?\d*)\s*Per` | "2 @ $150 Per 8m piece" | qty=2, unit_price=150, basis=per_unit |
| `@\s*\$?([\d,]+\.?\d*)\s*For This Event` | "@ $320.00 For This Event" | value=320, basis=flat |
| `(\d+)\s*Guards.*?(\d+:\d+)\s*[-–]\s*(\d+:\d+).*?@\s*\$?([\d,]+\.?\d*)` | "8 Guards 11:00-16:30 @ $71" | guards=8, hours=5.5, rate=71, basis=hourly |

**Money type detection:**
- Contains "on consumption" → `money_type="consumption"`, `needs_manual_value=True`
- Contains "at guest expense" → `money_type="cash"`, `needs_manual_value=True`
- Has `@` price → `money_type="contracted"`
- AV with "bill direct" → `money_type="external"`

**Failure handling:** Unrecognized lines flagged with `needs_manual_value=True` for human review.

## Builder

Computes category totals from validated EventOrder.

**Logic:**
```python
def compute_totals(event: EventOrder) -> WorksheetOutput:
    by_category = group_by(event.line_items, key=lambda x: x.category)

    totals = []
    for category, lines in by_category.items():
        # Delphi = all lines (contracted + consumption + cash)
        delphi_total = sum(line.value for line in lines)

        # Opera = exclude cash (only contracted + consumption)
        opera_total = sum(
            line.value for line in lines
            if line.money_type != "cash"
        )

        totals.append(CategoryTotals(
            category=category,
            delphi_total=delphi_total,
            opera_total=opera_total
        ))

    return WorksheetOutput(...)
```

**Rounding:** Round each line value to 2 decimal places at input; sum the rounded values.

**Excel output:**
- Sheet 1: Category totals table (Food/Beverage/Resource/Other/Venue Hire with Delphi and Opera columns)
- Sheet 2: Full line items for audit trail

**Golden test:** Must reproduce BEO 2895 targets: Delphi 210,079.60, Opera 205,230.63.

## Reconciler

Compares computed worksheet against Delphi posting report.

**Delphi ingestion:** Parse uploaded Excel, extract category → amount mapping.

**Comparison:** For each category, compare expected (computed) vs posted (Delphi).

**Rounding tolerance:** ±5 cents (Delphi has occasional 1-2 cent rounding drift).

**Diagnostic heuristics:**

| Condition | Likely Cause |
|-----------|--------------|
| Variance ≈ cash line value | "Cash sale posted to Opera by mistake (or vice versa)" |
| Variance ≈ consumption line value | "Consumption not keyed, or keyed to wrong category" |
| Variance / expected ≈ 0.10 or 1/11 | "GST treatment mismatch" |
| Variance = exact line value | "Line not posted" |
| Category missing from Delphi | "Entire category not posted" |
| Within ±5 cents | "Rounding only, no action" |

## UI Flow

Four-step Streamlit wizard with session state.

**Step 1: Upload & Extract**
- File uploader for EO PDF
- BEO selector if multiple BEOs in PDF
- Editable table showing extracted lines
- Lines needing manual values highlighted
- "Confirm extraction" to proceed

**Step 2: Complete Values**
- Shows only lines where `needs_manual_value=True`
- Input fields for consumption/cash values
- Running totals displayed
- "Values complete" to proceed

**Step 3: Generate Worksheet**
- Category totals table displayed
- Grand totals shown
- "Download worksheet" button (.xlsx)
- "Proceed to reconciliation" or "Done"

**Step 4: Reconcile**
- File uploader for Delphi report (.xlsx)
- Results table: Category | Expected | Posted | Variance | Likely Cause
- Color coding: red (discrepancy), green (match), grey (rounding only)
- "Download reconciliation report" button

**Navigation:**
- Progress indicator at top
- Back button on each step
- Session state preserves data (lost on refresh)

**Auth:** Streamlit built-in password auth via secrets.toml.

## Project Structure

```
event-recon/
├── app.py                  # Streamlit entry, wizard flow
├── recon/
│   ├── __init__.py
│   ├── models.py           # Pydantic schemas
│   ├── parser.py           # PDF extraction + pattern matching
│   ├── builder.py          # Compute totals, generate Excel
│   ├── reconciler.py       # Compare vs Delphi, diagnostics
│   └── delphi_adapter.py   # Delphi Excel ingestion
├── tests/
│   ├── test_builder_golden.py   # Must hit 205,230.63 / 210,079.60
│   ├── test_parser.py
│   ├── test_reconciler.py
│   └── fixtures/
│       └── beo_2895.json        # Golden test fixture
├── .streamlit/
│   └── secrets.toml.example     # Template for auth password
├── requirements.txt
├── pyproject.toml
└── README.md
```

**Dependencies:**
- streamlit>=1.28
- pdfplumber>=0.10
- pydantic>=2.0
- openpyxl>=3.1
- pandas>=2.0
- pytest>=7.0

## Deployment

1. Push to GitHub repo
2. Connect repo to share.streamlit.io
3. Set secrets (password) in Streamlit Cloud dashboard
4. Team accesses via `https://<app-name>.streamlit.app`

**Security:**
- Password auth limits access
- No data persisted on server
- Financial data only exists during active session

## Testing Strategy

1. **Golden test (first):** Builder reproduces BEO 2895 totals exactly
2. **Parser tests:** Known patterns extract correctly
3. **Reconciler tests:** Seeded discrepancies (cash-side, GST, missing line) correctly identified
4. **Integration:** End-to-end with sample PDFs provided by Zak

## Open Items

- Sample EO PDFs to be provided for parser testing
- Delphi export sample to finalize column mapping in adapter
- DDP split cheat sheet (future enhancement, not MVP)
