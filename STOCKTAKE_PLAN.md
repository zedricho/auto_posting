# Stocktake Tool Implementation Plan

## Current State Analysis

The Excel document (`Stocktake Master JAN 26.xlsx`) reveals a comprehensive inventory system with:

- **10 Departments** (sheets): CHEF, F&B, CHEF Need to Order, LOGISTICS, STEWARDING, Glass Studio, F&E, Items for confirm, Isoletto, FULL LIST
- **Sub-categories** within departments (e.g., F&B has BAR, COFFEE CART, CUTLERY, CUPS/GLASSWARE, PLATES/BOWLS/CROCKERY, TEA+COFFEE, etc.)
- **456 total items** across all departments
- **Key fields**: Item Code (TSB-XXX-NNNN), Name, Supplier, Par Level, Warehouse/Onsite counts, Stock Down calculation, Selling Price

### Excel Column Structure

| Column | Description | Example |
|--------|-------------|---------|
| PHOTO | Item image | - |
| TSB INTERNAL ITEM CODE | Unique identifier | TSB-KIT-A001, TSB-FAB-A001 |
| EVENTS NAME | Display name | "500ml Mixing Bowl" |
| SUPPLIER | Supplier company | TRENTON, QCC |
| CODE | Supplier product code | 72004 |
| SUPPLIER NAME | Full description | "BOWL MIXING S/S 500ML 160X50MM" |
| PAR LEVEL | Minimum stock level | 24 |
| Warehouse | Warehouse count | 0 |
| Onsite | Onsite count | 24 |
| Date columns | Historical counts | 2024-08-01, 2025-01-01 |
| STOCK DOWN | Formula: PAR - current | 0 |
| SELL (ex GST) | Selling price | 1.42 |
| SIZE | Unit type | EACH |

### Department Breakdown

| Department | Items | Categories |
|------------|-------|------------|
| CHEF | 163 | Kitchen equipment, mixing bowls, cutting boards |
| F&B | 297 | BAR, COFFEE CART, CUTLERY, CUPS/GLASSWARE, PLATES/BOWLS, TEA+COFFEE |
| LOGISTICS | 28 | Power boxes, flipcharts, extension cables |
| STEWARDING | 32 | Bins, cleaning supplies |
| Glass Studio | 86 | Premium glass items, cake stands |
| F&E | 109 | Dance floors, furniture |
| Items for confirm | TBD | Pending confirmation |
| Isoletto | TBD | Location-specific items |

---

## Proposed Architecture

### 1. Data Models (`recon/stocktake.py`)

```python
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

@dataclass
class StockItem:
    """A single inventory item."""
    item_code: str           # TSB-KIT-A001
    name: str                # "500ml Mixing Bowl"
    department: str          # "CHEF"
    category: str            # Optional sub-category like "BAR"
    supplier: str            # "TRENTON"
    supplier_code: str       # "72004"
    supplier_name: str       # Full description
    par_level: int           # Minimum stock level
    selling_price: float     # Ex GST
    size: str                # "EACH"

@dataclass
class StocktakeCount:
    """A count for a single item."""
    item_code: str
    date: date
    warehouse: int
    onsite: int
    total: int               # warehouse + onsite (computed)
    stock_down: int          # par_level - total (computed)

@dataclass
class StocktakeSession:
    """A stocktake session (one counting event)."""
    session_id: str
    date: date
    location: str            # "Warehouse" or "Onsite" or "Both"
    counts: List[StocktakeCount] = field(default_factory=list)
    completed_by: str = ""
    status: str = "in_progress"  # "in_progress", "completed"
    notes: str = ""
```

### 2. Storage Layer (`recon/stocktake_db.py`)

```python
# JSON file storage
ITEMS_FILE = "data/stocktake_items.json"
COUNTS_FILE = "data/stocktake_counts.json"
SESSIONS_FILE = "data/stocktake_sessions.json"

def load_items() -> List[StockItem]: ...
def save_items(items: List[StockItem]) -> None: ...
def load_counts(session_id: Optional[str] = None) -> List[StocktakeCount]: ...
def save_counts(counts: List[StocktakeCount], session_id: str) -> None: ...
def import_from_excel(file_path: str) -> List[StockItem]: ...
def export_to_excel(session_id: str) -> bytes: ...
```

### 3. UI Design (new page in `app.py`)

```
Stocktake Page
├── Import Section (one-time setup from Excel)
│   └── Upload Master Excel → Parse → Store items
│
├── New Stocktake Session
│   ├── Select Date
│   ├── Select Location (Warehouse / Onsite / Both)
│   └── Start Count → Creates session
│
├── Count Entry (main workflow)
│   ├── Department Tabs (CHEF, F&B, LOGISTICS...)
│   │   └── Category Sections (expandable accordions)
│   │       └── Item rows with:
│   │           - Item code & name
│   │           - Par level (reference)
│   │           - Warehouse input
│   │           - Onsite input
│   │           - Stock Down (auto-calculated)
│   │           - Alert indicator if below par
│   │
│   ├── Quick Search (by code or name)
│   └── Progress indicator (X of Y items counted)
│
├── Review & Submit
│   ├── Summary by department
│   ├── Stock down alerts
│   └── Submit / Complete session
│
└── History & Reports
    ├── Compare counts over time
    ├── Variance reports
    └── Export to Excel
```

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Excel Import** | One-time import of existing master list from Excel |
| **Department Tabs** | Navigate by department (CHEF, F&B, LOGISTICS, etc.) |
| **Category Grouping** | Group items by sub-category within departments |
| **Quick Count Entry** | Simple number inputs with +/- buttons |
| **Real-time Stock Down** | Auto-calculate par level - current count |
| **Visual Alerts** | Highlight items below par level (red/orange) |
| **Search** | Find items by code or name across all departments |
| **Session Tracking** | Track who counted, when, completion status |
| **History** | View and compare counts over time |
| **Export** | Generate Excel in same format as original |

---

## Implementation Steps

### Phase 1: Foundation
1. Create data models - `recon/stocktake.py`
2. Create storage layer - `recon/stocktake_db.py`
3. Build Excel importer - Parse master Excel file
4. Add unit tests for models and storage

### Phase 2: UI
5. Add "Stocktake" page to sidebar navigation
6. Build import UI (upload Excel, preview, confirm)
7. Build count entry UI:
   - Department tabs
   - Category expandable sections
   - Item rows with inputs
8. Add search functionality

### Phase 3: Features
9. Implement stock down calculations with visual alerts
10. Add session management (start, pause, complete)
11. Create export function (Excel in original format)
12. Add history/comparison views

### Phase 4: Polish
13. Mobile-responsive design for tablet counting
14. Add batch entry mode (scan and enter)
15. Performance optimization for large item lists

---

## Improvements Over Excel

| Current Excel | New Tool |
|---------------|----------|
| Manual formula updates | Auto-calculated stock down |
| Single file, single user | Multi-user with session tracking |
| Easy to overwrite data | Historical data preserved |
| Desktop only | Mobile-friendly for warehouse counting |
| Manual search (Ctrl+F) | Instant search by code/name |
| No validation | Input validation, unusual count warnings |
| Manual backups | Automatic version history |

---

## Technical Notes

### Item Code Format
- Pattern: `TSB-{DEPT}-{CATEGORY}{NUMBER}`
- Examples:
  - `TSB-KIT-A001` - Kitchen item
  - `TSB-FAB-A001` - F&B item
  - `TSB-LOG-A001` - Logistics item
  - `TSB-STW-A001` - Stewarding item
  - `TSB-GST-0001` - Glass Studio item
  - `TSB-FFE-A001` - F&E item

### Department Codes
| Code | Department |
|------|------------|
| KIT | CHEF (Kitchen) |
| FAB | F&B |
| LOG | LOGISTICS |
| STW | STEWARDING |
| GST | Glass Studio |
| FFE | F&E (Furniture & Equipment) |

### Stock Down Formula
```
STOCK DOWN = PAR LEVEL - (Warehouse + Onsite)
```
- If negative: Item is overstocked
- If zero: At par level
- If positive: Item needs reordering

---

## File References

- Master Excel: `Stocktake Master JAN 26.xlsx`
- This plan: `STOCKTAKE_PLAN.md`

---

*Plan created: June 2025*
*Status: Pending implementation*
