"""Stocktake: data models and Excel import/export."""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Dict, List, Optional
import json
import os
import re
import uuid

import pandas as pd


@dataclass
class StockItem:
    """A single inventory item."""
    item_code: str           # TSB-KIT-A001
    name: str                # "500ml Mixing Bowl"
    department: str          # "CHEF"
    category: str            # Sub-category like "BAR"
    supplier: str            # "TRENTON"
    supplier_code: str       # "72004"
    supplier_name: str       # Full description
    par_level: int           # Minimum stock level
    selling_price: float     # Ex GST
    size: str                # "EACH"

    def to_dict(self) -> dict:
        return {
            "item_code": self.item_code,
            "name": self.name,
            "department": self.department,
            "category": self.category,
            "supplier": self.supplier,
            "supplier_code": self.supplier_code,
            "supplier_name": self.supplier_name,
            "par_level": self.par_level,
            "selling_price": self.selling_price,
            "size": self.size,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StockItem":
        return cls(
            item_code=data["item_code"],
            name=data["name"],
            department=data["department"],
            category=data.get("category", ""),
            supplier=data.get("supplier", ""),
            supplier_code=data.get("supplier_code", ""),
            supplier_name=data.get("supplier_name", ""),
            par_level=data.get("par_level", 0),
            selling_price=data.get("selling_price", 0.0),
            size=data.get("size", "EACH"),
        )


@dataclass
class BaseItem:
    """A base inventory item with Jan 26 counts (read-only reference data)."""
    item_code: str           # TSB-FAB-A001
    name: str                # "Bar Blade"
    department: str          # "F&B"
    jan26_inhouse: int       # Count from Jan 26 stocktake
    warehouse: int           # Warehouse count
    total: int               # Total count

    def to_dict(self) -> dict:
        return {
            "item_code": self.item_code,
            "name": self.name,
            "department": self.department,
            "jan26_inhouse": self.jan26_inhouse,
            "warehouse": self.warehouse,
            "total": self.total,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BaseItem":
        return cls(
            item_code=data["item_code"],
            name=data["name"],
            department=data["department"],
            jan26_inhouse=data.get("jan26_inhouse", 0),
            warehouse=data.get("warehouse", 0),
            total=data.get("total", 0),
        )


# Department mapping from item code prefix
DEPT_CODE_MAP = {
    "FAB": "F&B",
    "KIT": "CHEF",
    "LOG": "LOGISTICS",
    "STW": "STEWARDING",
    "GST": "Glass Studio",
    "GH": "Glass Studio",  # Alternative code for Glass items
    "FFE": "F&E",
}


def get_department_from_code(item_code: str) -> str:
    """Extract department from item code like TSB-FAB-A001."""
    if not item_code or not item_code.startswith("TSB-"):
        return "Unknown"
    parts = item_code.split("-")
    if len(parts) >= 2:
        prefix = parts[1]
        return DEPT_CODE_MAP.get(prefix, "Unknown")
    return "Unknown"


@dataclass
class StocktakeCount:
    """A count for a single item in a session."""
    item_code: str
    warehouse: int = 0
    onsite: int = 0

    @property
    def total(self) -> int:
        return self.warehouse + self.onsite

    def stock_down(self, par_level: int) -> int:
        """Calculate how many items are below par level."""
        return par_level - self.total

    def to_dict(self) -> dict:
        return {
            "item_code": self.item_code,
            "warehouse": self.warehouse,
            "onsite": self.onsite,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StocktakeCount":
        return cls(
            item_code=data["item_code"],
            warehouse=data.get("warehouse", 0),
            onsite=data.get("onsite", 0),
        )


@dataclass
class StocktakeSession:
    """A stocktake session (one counting event)."""
    session_id: str
    session_date: date
    location: str = "Both"  # "Warehouse", "Onsite", or "Both"
    counts: Dict[str, StocktakeCount] = field(default_factory=dict)  # item_code -> count
    completed_by: str = ""
    status: str = "in_progress"  # "in_progress", "completed"
    notes: str = ""
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at

    def get_count(self, item_code: str) -> StocktakeCount:
        """Get or create a count for an item."""
        if item_code not in self.counts:
            self.counts[item_code] = StocktakeCount(item_code=item_code)
        return self.counts[item_code]

    def set_count(self, item_code: str, warehouse: int, onsite: int):
        """Set the count for an item."""
        self.counts[item_code] = StocktakeCount(
            item_code=item_code,
            warehouse=warehouse,
            onsite=onsite,
        )
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "session_date": self.session_date.isoformat(),
            "location": self.location,
            "counts": {k: v.to_dict() for k, v in self.counts.items()},
            "completed_by": self.completed_by,
            "status": self.status,
            "notes": self.notes,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StocktakeSession":
        counts = {
            k: StocktakeCount.from_dict(v)
            for k, v in data.get("counts", {}).items()
        }
        return cls(
            session_id=data["session_id"],
            session_date=date.fromisoformat(data["session_date"]),
            location=data.get("location", "Both"),
            counts=counts,
            completed_by=data.get("completed_by", ""),
            status=data.get("status", "in_progress"),
            notes=data.get("notes", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


# Department display names and order
DEPARTMENTS = [
    ("CHEF", "Chef / Kitchen"),
    ("F&B", "Food & Beverage"),
    ("LOGISTICS", "Logistics"),
    ("STEWARDING", "Stewarding"),
    ("Glass Studio", "Glass Studio"),
    ("F&E", "Furniture & Equipment"),
]

# Sheets to skip when importing
SKIP_SHEETS = ["CHEF Need to Order", "Items for confirm", "Isoletto", "FULL LIST"]


def import_from_excel(file_path: str) -> List[StockItem]:
    """
    Import stock items from the master Excel file.

    Parses each department sheet and extracts item data.
    Returns a list of StockItem objects.
    """
    xl = pd.ExcelFile(file_path)
    items = []

    for sheet_name in xl.sheet_names:
        # Skip non-inventory sheets
        if sheet_name in SKIP_SHEETS:
            continue

        df = pd.read_excel(xl, sheet_name=sheet_name, header=None)

        if df.empty:
            continue

        # Find the header row (contains "TSB INTERNAL ITEM CODE")
        header_row = None
        for idx, row in df.iterrows():
            row_str = ' '.join(str(v) for v in row.values if pd.notna(v))
            if 'TSB INTERNAL ITEM CODE' in row_str.upper() or 'INTERNAL ITEM CODE' in row_str.upper():
                header_row = idx
                break

        if header_row is None:
            continue

        # Get column indices from header row
        header = df.iloc[header_row]
        col_map = {}
        for col_idx, val in enumerate(header):
            if pd.isna(val):
                continue
            val_upper = str(val).upper().strip()
            if 'INTERNAL ITEM CODE' in val_upper:
                col_map['item_code'] = col_idx
            elif val_upper == 'EVENTS NAME':
                col_map['name'] = col_idx
            elif val_upper == 'SUPPLIER' and 'NAME' not in val_upper:
                col_map['supplier'] = col_idx
            elif val_upper == 'CODE' and 'ITEM' not in val_upper:
                col_map['supplier_code'] = col_idx
            elif val_upper == 'SUPPLIER NAME':
                col_map['supplier_name'] = col_idx
            elif val_upper == 'PAR LEVEL':
                col_map['par_level'] = col_idx
            elif 'SELL' in val_upper and 'GST' in val_upper:
                col_map['selling_price'] = col_idx
            elif val_upper == 'SIZE':
                col_map['size'] = col_idx

        if 'item_code' not in col_map:
            continue

        # Parse items (rows after header)
        current_category = ""
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx]

            # Check for category header (text in first column, no item code)
            first_col = row.iloc[0] if pd.notna(row.iloc[0]) else ""
            item_code_col = col_map.get('item_code', 1)
            item_code = row.iloc[item_code_col] if pd.notna(row.iloc[item_code_col]) else ""

            # Category header detection
            if first_col and not item_code:
                first_col_str = str(first_col).strip()
                # Skip department headers (same as sheet name) and common non-category text
                if first_col_str.upper() not in [sheet_name.upper(), 'PHOTO', 'NAN', '']:
                    if not re.match(r'^[\d\.\$]', first_col_str):  # Not a number or price
                        current_category = first_col_str
                continue

            # Skip rows without item code
            if not item_code or not str(item_code).startswith('TSB-'):
                continue

            # Extract item data
            def get_val(key, default=""):
                if key not in col_map:
                    return default
                val = row.iloc[col_map[key]]
                if pd.isna(val):
                    return default
                return val

            name = str(get_val('name', '')).strip()
            if not name:
                name = str(get_val('supplier_name', item_code)).strip()

            # Parse par level
            par_level_raw = get_val('par_level', 0)
            try:
                par_level = int(float(par_level_raw)) if par_level_raw else 0
            except (ValueError, TypeError):
                par_level = 0

            # Parse selling price
            price_raw = get_val('selling_price', 0)
            try:
                if isinstance(price_raw, str):
                    price_raw = price_raw.replace('$', '').replace(',', '')
                selling_price = float(price_raw) if price_raw else 0.0
            except (ValueError, TypeError):
                selling_price = 0.0

            item = StockItem(
                item_code=str(item_code).strip(),
                name=name,
                department=sheet_name,
                category=current_category,
                supplier=str(get_val('supplier', '')).strip(),
                supplier_code=str(get_val('supplier_code', '')).strip(),
                supplier_name=str(get_val('supplier_name', '')).strip(),
                par_level=par_level,
                selling_price=selling_price,
                size=str(get_val('size', 'EACH')).strip(),
            )
            items.append(item)

    return items


def create_session(session_date: date, location: str = "Both") -> StocktakeSession:
    """Create a new stocktake session."""
    return StocktakeSession(
        session_id=str(uuid.uuid4())[:8],
        session_date=session_date,
        location=location,
    )


def export_to_excel(items: List[StockItem], session: StocktakeSession) -> bytes:
    """
    Export a stocktake session to Excel.

    Returns bytes of the Excel file.
    """
    from io import BytesIO
    import xlsxwriter

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})

    # Formats
    header_fmt = workbook.add_format({
        "bold": True,
        "bg_color": "#4472C4",
        "font_color": "white",
        "border": 1,
    })
    category_fmt = workbook.add_format({
        "bold": True,
        "bg_color": "#D9D9D9",
        "border": 1,
    })
    cell_fmt = workbook.add_format({"border": 1})
    number_fmt = workbook.add_format({"border": 1, "num_format": "0"})
    alert_fmt = workbook.add_format({
        "border": 1,
        "bg_color": "#FFC7CE",
        "font_color": "#9C0006",
    })

    # Group items by department
    by_dept: Dict[str, List[StockItem]] = {}
    for item in items:
        if item.department not in by_dept:
            by_dept[item.department] = []
        by_dept[item.department].append(item)

    # Create a sheet for each department
    for dept_code, dept_name in DEPARTMENTS:
        if dept_code not in by_dept:
            continue

        dept_items = by_dept[dept_code]
        ws = workbook.add_worksheet(dept_code[:31])  # Sheet names max 31 chars

        # Headers
        headers = ["Item Code", "Name", "Category", "Par Level", "Warehouse", "Onsite", "Total", "Stock Down"]
        for col, header in enumerate(headers):
            ws.write(0, col, header, header_fmt)

        # Column widths
        ws.set_column(0, 0, 15)  # Item Code
        ws.set_column(1, 1, 35)  # Name
        ws.set_column(2, 2, 15)  # Category
        ws.set_column(3, 7, 12)  # Numbers

        row = 1
        current_category = None

        for item in dept_items:
            # Category header
            if item.category and item.category != current_category:
                current_category = item.category
                ws.merge_range(row, 0, row, 7, current_category, category_fmt)
                row += 1

            count = session.get_count(item.item_code)
            stock_down = count.stock_down(item.par_level)

            ws.write(row, 0, item.item_code, cell_fmt)
            ws.write(row, 1, item.name, cell_fmt)
            ws.write(row, 2, item.category, cell_fmt)
            ws.write(row, 3, item.par_level, number_fmt)
            ws.write(row, 4, count.warehouse, number_fmt)
            ws.write(row, 5, count.onsite, number_fmt)
            ws.write(row, 6, count.total, number_fmt)

            # Highlight if below par
            fmt = alert_fmt if stock_down > 0 else number_fmt
            ws.write(row, 7, stock_down, fmt)

            row += 1

    # Summary sheet
    ws_summary = workbook.add_worksheet("Summary")
    ws_summary.write(0, 0, "Stocktake Summary", header_fmt)
    ws_summary.write(1, 0, f"Date: {session.session_date}")
    ws_summary.write(2, 0, f"Location: {session.location}")
    ws_summary.write(3, 0, f"Status: {session.status}")
    ws_summary.write(4, 0, f"Completed By: {session.completed_by}")

    # Count summary
    ws_summary.write(6, 0, "Department", header_fmt)
    ws_summary.write(6, 1, "Items", header_fmt)
    ws_summary.write(6, 2, "Below Par", header_fmt)

    row = 7
    for dept_code, dept_name in DEPARTMENTS:
        if dept_code not in by_dept:
            continue
        dept_items = by_dept[dept_code]
        below_par = sum(
            1 for item in dept_items
            if session.get_count(item.item_code).stock_down(item.par_level) > 0
        )
        ws_summary.write(row, 0, dept_name, cell_fmt)
        ws_summary.write(row, 1, len(dept_items), number_fmt)
        ws_summary.write(row, 2, below_par, alert_fmt if below_par > 0 else number_fmt)
        row += 1

    workbook.close()
    output.seek(0)
    return output.read()


# Storage functions
DATA_DIR = "data"
ITEMS_FILE = os.path.join(DATA_DIR, "stocktake_items.json")
SESSIONS_FILE = os.path.join(DATA_DIR, "stocktake_sessions.json")
BASE_FILE = os.path.join(DATA_DIR, "stocktake_base.json")


def _ensure_data_dir():
    """Ensure the data directory exists."""
    os.makedirs(DATA_DIR, exist_ok=True)


def import_base_from_excel(file_path: str) -> List[BaseItem]:
    """
    Import base stocktake data from the Jan 26 results Excel.

    Uses Sheet1 with columns:
    - B: TSB INTERNAL ITEM CODE
    - C: EVENTS NAME
    - H: Jan-26 In house
    - I: Warehouse
    - J: Jan26 TOTAL
    """
    df = pd.read_excel(file_path, sheet_name="Sheet1", header=0)
    df.columns = [str(c).strip() for c in df.columns]

    items = []
    for _, row in df.iterrows():
        item_code = str(row.get("TSB INTERNAL ITEM CODE", "")).strip()
        if not item_code.startswith("TSB-"):
            continue

        name = str(row.get("EVENTS NAME", "")).strip()
        if not name or name == "nan":
            name = item_code

        # Parse counts (handle NaN and floats)
        def safe_int(val, default=0):
            try:
                if pd.isna(val):
                    return default
                return int(float(val))
            except (ValueError, TypeError):
                return default

        jan26_inhouse = safe_int(row.get("Jan-26 In house", 0))
        warehouse = safe_int(row.get("Warehouse", 0))
        total = safe_int(row.get("Jan26 TOTAL", 0))

        department = get_department_from_code(item_code)

        items.append(BaseItem(
            item_code=item_code,
            name=name,
            department=department,
            jan26_inhouse=jan26_inhouse,
            warehouse=warehouse,
            total=total,
        ))

    return items


def load_base_items() -> List[BaseItem]:
    """Load base items from JSON storage."""
    _ensure_data_dir()
    if not os.path.exists(BASE_FILE):
        return []
    with open(BASE_FILE, "r") as f:
        data = json.load(f)
    return [BaseItem.from_dict(d) for d in data]


def save_base_items(items: List[BaseItem]):
    """Save base items to JSON storage."""
    _ensure_data_dir()
    data = [item.to_dict() for item in items]
    with open(BASE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_base_by_department(items: List[BaseItem]) -> Dict[str, List[BaseItem]]:
    """Group base items by department."""
    by_dept: Dict[str, List[BaseItem]] = {}
    for item in items:
        if item.department not in by_dept:
            by_dept[item.department] = []
        by_dept[item.department].append(item)
    return by_dept


def load_items() -> List[StockItem]:
    """Load stock items from JSON storage."""
    _ensure_data_dir()
    if not os.path.exists(ITEMS_FILE):
        return []
    with open(ITEMS_FILE, "r") as f:
        data = json.load(f)
    return [StockItem.from_dict(d) for d in data]


def save_items(items: List[StockItem]):
    """Save stock items to JSON storage."""
    _ensure_data_dir()
    data = [item.to_dict() for item in items]
    with open(ITEMS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def load_sessions() -> List[StocktakeSession]:
    """Load all stocktake sessions from JSON storage."""
    _ensure_data_dir()
    if not os.path.exists(SESSIONS_FILE):
        return []
    with open(SESSIONS_FILE, "r") as f:
        data = json.load(f)
    return [StocktakeSession.from_dict(d) for d in data]


def save_session(session: StocktakeSession):
    """Save a stocktake session (creates or updates)."""
    sessions = load_sessions()

    # Find and update existing, or append new
    found = False
    for i, s in enumerate(sessions):
        if s.session_id == session.session_id:
            sessions[i] = session
            found = True
            break

    if not found:
        sessions.append(session)

    _ensure_data_dir()
    data = [s.to_dict() for s in sessions]
    with open(SESSIONS_FILE, "w") as f:
        json.dump(data, f, indent=2)


def get_session(session_id: str) -> Optional[StocktakeSession]:
    """Get a specific session by ID."""
    sessions = load_sessions()
    for s in sessions:
        if s.session_id == session_id:
            return s
    return None


def get_items_by_department(items: List[StockItem]) -> Dict[str, List[StockItem]]:
    """Group items by department."""
    by_dept: Dict[str, List[StockItem]] = {}
    for item in items:
        if item.department not in by_dept:
            by_dept[item.department] = []
        by_dept[item.department].append(item)
    return by_dept


def get_items_by_category(items: List[StockItem]) -> Dict[str, Dict[str, List[StockItem]]]:
    """Group items by department, then by category."""
    result: Dict[str, Dict[str, List[StockItem]]] = {}
    for item in items:
        if item.department not in result:
            result[item.department] = {}
        cat = item.category or "Uncategorized"
        if cat not in result[item.department]:
            result[item.department][cat] = []
        result[item.department][cat].append(item)
    return result
