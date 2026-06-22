"""Packing List Generator: data model and calculations for event packing sheets."""

import json
import math
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class PackingItem:
    """Definition of a packable item with quantity formula."""
    id: str
    name: str
    category: str  # linen, table_set, kitchen, tc, service, bar_boh, bar_foh

    # Quantity calculation
    formula: str  # "per_pax", "per_table", "per_pax_1.5", "per_table_2", "per_table_3", "fixed_5", "per_10_tables"

    # Conditional inclusion
    condition: Optional[str] = None  # "has_entree", "has_dessert", "has_tc", "has_foh_bar", "has_canapes"

    # Display
    default_notes: str = ""

    def calculate_qty(self, pax: int, tables: int, options: Dict[str, bool]) -> int:
        """Calculate quantity based on formula and event config."""
        # Check condition first
        if self.condition:
            if not options.get(self.condition, False):
                return 0

        # Calculate based on formula
        if self.formula == "per_pax":
            return pax
        elif self.formula == "per_pax_1.5":
            return math.ceil(pax * 1.5)
        elif self.formula == "per_pax_2":
            return pax * 2
        elif self.formula == "per_table":
            return tables
        elif self.formula == "per_table_2":
            return tables * 2
        elif self.formula == "per_table_3":
            return tables * 3
        elif self.formula == "per_10_tables":
            return math.ceil(tables / 10)
        elif self.formula.startswith("fixed_"):
            return int(self.formula.split("_")[1])
        else:
            return 0


@dataclass
class PackingListItem:
    """An item in a specific packing list with quantities."""
    item_id: str
    name: str
    category: str
    suggested_qty: int
    final_qty: int
    packed: bool = False
    notes: str = ""


@dataclass
class PackingList:
    """A complete packing list for an event."""
    id: str
    event_name: str
    event_date: Optional[date]
    location: str
    pax: int
    tables: int

    # Configuration options
    courses: int  # 1, 2, or 3
    has_entree: bool
    has_dessert: bool
    has_tc: bool  # Preset tea & coffee
    has_foh_bar: bool
    has_canapes: bool
    napkin_color: str  # "black" or "white"
    underliner_color: str  # "black" or "white"
    round_color: str  # "black" or "white" (tablecloths)

    # Items
    items: List[PackingListItem] = field(default_factory=list)

    # Metadata
    created_at: str = ""
    status: str = "draft"  # draft, finalized

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if self.event_date:
            result["event_date"] = self.event_date.isoformat()
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PackingList":
        if data.get("event_date"):
            data["event_date"] = date.fromisoformat(data["event_date"])
        items = [PackingListItem(**item) for item in data.pop("items", [])]
        return cls(**data, items=items)


# ============ ITEM DATABASE ============
# All items for plated dinners with their formulas

PACKING_ITEMS: List[PackingItem] = [
    # === LINEN ===
    PackingItem("black_napkins", "Black Napkins", "linen", "per_pax",
                condition=None, default_notes="Book folded"),
    PackingItem("white_napkins", "White Napkins", "linen", "per_pax",
                condition=None, default_notes="Book folded"),
    PackingItem("black_rounds", "Black Rounds", "linen", "per_table",
                condition=None, default_notes="Tablecloths"),
    PackingItem("white_rounds", "White Rounds", "linen", "per_table",
                condition=None, default_notes="Tablecloths"),

    # === TABLE SET ===
    PackingItem("side_plate", "Side Plate", "table_set", "per_pax"),
    # Note: Entrée fork uses special "per_pax_or_2x" formula - handled in generate_packing_list
    PackingItem("entree_fork", "Entrée Fork", "table_set", "per_pax",
                condition="has_entree", default_notes="Dessert fork size"),
    PackingItem("entree_knife", "Entrée Knife", "table_set", "per_pax_2",
                condition="has_entree", default_notes="+ bread knife"),
    PackingItem("main_fork", "Main Fork", "table_set", "per_pax",
                condition="has_entree"),
    PackingItem("main_knife", "Main Knife", "table_set", "per_pax",
                condition="has_entree"),
    PackingItem("dessert_spoon", "Dessert Spoon", "table_set", "per_pax",
                condition="has_dessert"),
    PackingItem("water_glass", "Water Glass", "table_set", "per_pax"),
    PackingItem("wine_glass", "Wine Glass", "table_set", "per_pax"),
    PackingItem("tea_cup", "Tea Cup", "table_set", "per_pax",
                condition="has_tc"),
    PackingItem("saucer", "Saucer", "table_set", "per_pax",
                condition="has_tc"),
    PackingItem("tea_spoon", "Tea Spoon", "table_set", "per_pax",
                condition="has_tc"),
    PackingItem("black_underliner", "Black Underliner Plate", "table_set", "per_table_3"),
    PackingItem("white_underliner", "White Underliner Plate", "table_set", "per_table_3"),
    PackingItem("table_numbers", "Table Numbers & Stands", "table_set", "per_table"),
    PackingItem("menu_holders", "Menu Holders", "table_set", "per_table"),
    PackingItem("salt_pepper", "Salt & Pepper Sets", "table_set", "per_table",
                default_notes="1 set per table"),

    # === KITCHEN ===
    PackingItem("bread_basket", "Bread Basket", "kitchen", "per_table_2",
                default_notes="With linen napkin"),
    PackingItem("butter_dishes", "Butter Dishes", "kitchen", "per_table_2"),

    # === T&C SERVICE ===
    PackingItem("tc_center", "Tea & Coffee Center", "tc", "per_table_2",
                condition="has_tc"),
    PackingItem("tc_trays", "T&C Service Trays", "tc", "fixed_5",
                condition="has_tc", default_notes="Saucers, cups, teaspoons"),

    # === OTHER SERVICE ===
    PackingItem("jack_trays", "Jack Trays", "service", "per_10_tables"),
    PackingItem("jack_tray_legs", "Jack Tray Legs", "service", "per_10_tables"),
    PackingItem("jack_tray_linen", "Jack Tray Linen", "service", "per_10_tables",
                default_notes="Square 224x224"),

    # === BAR - BOH ===
    PackingItem("bar_wine_glass", "Wine Glass (Bar)", "bar_boh", "per_pax_1.5"),
    PackingItem("bar_champagne", "Champagne Glass", "bar_boh", "per_pax_1.5"),
    PackingItem("bar_beer", "Beer Glass", "bar_boh", "per_pax_1.5"),
    PackingItem("bar_rocks", "Rocks Glass", "bar_boh", "per_pax_1.5"),
    PackingItem("bar_non_alc", "Non-Alc Glass", "bar_boh", "per_pax_1.5"),

    # === BAR - FOH ===
    PackingItem("foh_wine_glass", "Wine Glass (FOH)", "bar_foh", "per_pax_1.5",
                condition="has_foh_bar"),
    PackingItem("foh_champagne", "Champagne Glass (FOH)", "bar_foh", "per_pax_1.5",
                condition="has_foh_bar"),
    PackingItem("foh_beer", "Beer Glass (FOH)", "bar_foh", "per_pax_1.5",
                condition="has_foh_bar"),
    PackingItem("foh_rocks", "Rocks Glass (FOH)", "bar_foh", "per_pax_1.5",
                condition="has_foh_bar"),
    PackingItem("foh_non_alc", "Non-Alc Glass (FOH)", "bar_foh", "per_pax_1.5",
                condition="has_foh_bar"),

    # === CANAPE ===
    PackingItem("silver_trays", "Silver Service Trays", "canape", "fixed_5",
                condition="has_canapes", default_notes="With non-slip mat"),
]

# Index by ID for quick lookup
ITEMS_BY_ID = {item.id: item for item in PACKING_ITEMS}

# Category display order and labels
CATEGORY_ORDER = ["linen", "table_set", "kitchen", "tc", "service", "bar_boh", "bar_foh", "canape"]
CATEGORY_LABELS = {
    "linen": "Linen",
    "table_set": "Table Set",
    "kitchen": "Kitchen",
    "tc": "Tea & Coffee",
    "service": "Other Service",
    "bar_boh": "Bar - BOH (Dispense)",
    "bar_foh": "Bar - FOH (If Required)",
    "canape": "Canapé Service",
}


def generate_packing_list(
    event_name: str,
    event_date: Optional[date],
    location: str,
    pax: int,
    tables: int,
    courses: int,
    has_tc: bool,
    has_foh_bar: bool,
    has_canapes: bool,
    napkin_color: str,
    underliner_color: str,
    round_color: str,
) -> PackingList:
    """Generate a packing list with calculated quantities."""

    # Derive conditions from courses
    has_entree = courses >= 2
    has_dessert = courses >= 2  # 2+ courses typically have dessert option

    options = {
        "has_entree": has_entree,
        "has_dessert": has_dessert,
        "has_tc": has_tc,
        "has_foh_bar": has_foh_bar,
        "has_canapes": has_canapes,
    }

    # Generate items
    items = []
    for item in PACKING_ITEMS:
        qty = item.calculate_qty(pax, tables, options)

        # Special case: Entrée fork needs 2x for 3-course (entrée + dessert)
        if item.id == "entree_fork" and courses == 3:
            qty = pax * 2

        # Handle color selection for napkins, underliners, and rounds
        # Napkins
        if item.id == "black_napkins" and napkin_color != "black":
            qty = 0
        elif item.id == "white_napkins" and napkin_color != "white":
            qty = 0
        # Underliners
        elif item.id == "black_underliner" and underliner_color != "black":
            qty = 0
        elif item.id == "white_underliner" and underliner_color != "white":
            qty = 0
        # Rounds (tablecloths)
        elif item.id == "black_rounds" and round_color != "black":
            qty = 0
        elif item.id == "white_rounds" and round_color != "white":
            qty = 0

        items.append(PackingListItem(
            item_id=item.id,
            name=item.name,
            category=item.category,
            suggested_qty=qty,
            final_qty=qty,
            packed=False,
            notes=item.default_notes,
        ))

    return PackingList(
        id=datetime.now().strftime("%Y%m%d_%H%M%S"),
        event_name=event_name,
        event_date=event_date,
        location=location,
        pax=pax,
        tables=tables,
        courses=courses,
        has_entree=has_entree,
        has_dessert=has_dessert,
        has_tc=has_tc,
        has_foh_bar=has_foh_bar,
        has_canapes=has_canapes,
        napkin_color=napkin_color,
        underliner_color=underliner_color,
        round_color=round_color,
        items=items,
        created_at=datetime.now().isoformat(),
        status="draft",
    )


def get_items_by_category(packing_list: PackingList) -> Dict[str, List[PackingListItem]]:
    """Group packing list items by category."""
    result = {cat: [] for cat in CATEGORY_ORDER}
    for item in packing_list.items:
        if item.category in result:
            result[item.category].append(item)
    return result


# ============ STORAGE ============

PACKING_LISTS_DIR = Path(__file__).parent.parent / "packing_lists"


def save_packing_list(packing_list: PackingList) -> Path:
    """Save a packing list to JSON file."""
    PACKING_LISTS_DIR.mkdir(exist_ok=True)
    filepath = PACKING_LISTS_DIR / f"{packing_list.id}.json"
    with open(filepath, "w") as f:
        json.dump(packing_list.to_dict(), f, indent=2)
    return filepath


def load_packing_list(list_id: str) -> Optional[PackingList]:
    """Load a packing list from JSON file."""
    filepath = PACKING_LISTS_DIR / f"{list_id}.json"
    if not filepath.exists():
        return None
    with open(filepath) as f:
        data = json.load(f)
    return PackingList.from_dict(data)


def list_saved_packing_lists() -> List[Dict[str, str]]:
    """List all saved packing lists."""
    if not PACKING_LISTS_DIR.exists():
        return []
    lists = []
    for filepath in PACKING_LISTS_DIR.glob("*.json"):
        try:
            with open(filepath) as f:
                data = json.load(f)
            lists.append({
                "id": data["id"],
                "event_name": data["event_name"],
                "event_date": data.get("event_date", ""),
                "status": data.get("status", "draft"),
            })
        except Exception:
            pass
    return sorted(lists, key=lambda x: x["id"], reverse=True)
