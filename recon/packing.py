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
    category: str

    # Quantity calculation
    formula: str  # "per_pax", "per_table", "per_pax_1.5", "per_table_2", "per_table_3", "fixed_N", "per_10_tables", "per_station", "per_buffet", "manual"

    # Conditional inclusion
    condition: Optional[str] = None

    # Display
    default_notes: str = ""

    def calculate_qty(self, pax: int, tables: int, stations: int, options: Dict[str, Any]) -> int:
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
        elif self.formula == "per_station":
            return stations
        elif self.formula == "per_buffet":
            return options.get("buffet_setups", 1)
        elif self.formula == "per_hot_item":
            return options.get("hot_items", 0)
        elif self.formula == "per_cold_item":
            return options.get("cold_items", 0)
        elif self.formula == "manual":
            return 0  # User fills in
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

    # Event type: "plated", "buffet", "plenary"
    event_type: str = "plated"

    # Sub-type for buffet/plenary
    sub_type: str = ""  # e.g., "breakfast", "lunch", "dinner" for buffet; "boardroom", "executive" for plenary

    # Plated-specific options
    courses: int = 2
    has_entree: bool = True
    has_dessert: bool = True

    # Common options
    has_tc: bool = False
    has_foh_bar: bool = False
    has_canapes: bool = False

    # Color options
    napkin_color: str = "black"
    underliner_color: str = "white"
    round_color: str = "black"

    # Buffet-specific options
    buffet_setups: int = 1
    hot_items: int = 0
    cold_items: int = 0
    tc_stations: int = 0
    water_stations: int = 0

    # Plenary-specific options
    trestle_count: int = 0

    # Items
    items: List[PackingListItem] = field(default_factory=list)

    # Metadata
    created_at: str = ""
    status: str = "draft"

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


# ============ EVENT TYPE DEFINITIONS ============

EVENT_TYPES = {
    "plated": "Plated Dinner",
    "buffet": "Buffet",
    "plenary": "Plenary / Boardroom",
}

BUFFET_SUB_TYPES = {
    "breakfast": "Buffet Breakfast",
    "morning_tea": "Buffet Morning Tea",
    "lunch": "Buffet Lunch",
    "afternoon_tea": "Buffet Afternoon Tea",
    "dinner": "Buffet Dinner",
    "mt_lunch": "Morning Tea & Lunch",
    "lunch_at": "Lunch & Afternoon Tea",
    "full_day": "Morning Tea, Lunch & Afternoon Tea",
}

PLENARY_SUB_TYPES = {
    "boardroom": "Boardroom - Plenary",
    "executive": "Boardroom - Executive",
}


# ============ PLATED ITEMS ============

PLATED_ITEMS: List[PackingItem] = [
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


# ============ BUFFET ITEMS ============

BUFFET_ITEMS: List[PackingItem] = [
    # === BUFFET SETUP ===
    PackingItem("buffet_underliner", "Underliner Plates", "buffet_setup", "manual"),
    PackingItem("buffet_entree_plate", "Entrée Plate", "buffet_setup", "per_pax"),
    PackingItem("buffet_entree_fork", "Entrée Fork", "buffet_setup", "per_pax",
                default_notes="Prepped in pocket fold or silver basket"),
    PackingItem("buffet_entree_knife", "Entrée Knife", "buffet_setup", "per_pax",
                default_notes="Prepped in pocket fold or silver basket"),
    PackingItem("buffet_dessert_spoon", "Dessert Spoon", "buffet_setup", "per_pax",
                condition="has_dessert"),
    PackingItem("buffet_tongs", "Tongs", "buffet_setup", "manual"),
    PackingItem("buffet_serving_spoon", "Serving Spoon", "buffet_setup", "manual"),
    PackingItem("buffet_tong_plates", "Tong Plates", "buffet_setup", "manual"),
    PackingItem("buffet_side_plates", "Side Plates", "buffet_setup", "manual",
                default_notes="For cocktail napkins"),
    PackingItem("white_riser_sets", "White Riser Sets", "buffet_setup", "per_cold_item",
                default_notes="1 set of each size per cold item"),
    PackingItem("black_riser_sets", "Black Riser Sets", "buffet_setup", "per_cold_item",
                default_notes="1 set of each size per cold item"),
    PackingItem("chaffing_dish", "Chaffing Dish", "buffet_setup", "per_hot_item",
                default_notes="Rectangular unless otherwise stated"),
    PackingItem("sternos", "Sternos", "buffet_setup", "manual",
                default_notes="2 per chaffing dish"),
    PackingItem("sterno_holders", "Sterno Holders", "buffet_setup", "manual"),
    PackingItem("rectangle_plate", "Rectangle Plate", "buffet_setup", "manual"),
    PackingItem("silver_baskets", "Silver Baskets", "buffet_setup", "manual"),
    PackingItem("linen_napkins_basket", "Linen Napkins (for baskets)", "buffet_setup", "manual"),
    PackingItem("salt_pepper_buffet", "Salt & Pepper Sets", "buffet_setup", "per_buffet"),
    PackingItem("a4_menu_holders", "A4 Acrylic Menu Holders", "buffet_setup", "per_buffet"),
    PackingItem("small_label_holders", "Small Acrylic Label Holders", "buffet_setup", "manual"),

    # === NAPKINS ===
    PackingItem("white_cocktail_napkins", "White Cocktail Napkins", "buffet_napkins", "fixed_1",
                default_notes="1 pack"),
    PackingItem("black_cocktail_napkins", "Black Cocktail Napkins", "buffet_napkins", "fixed_1",
                default_notes="1 pack"),
    PackingItem("white_dinner_napkins", "White Dinner Napkins", "buffet_napkins", "fixed_1",
                default_notes="1 pack"),
    PackingItem("black_dinner_napkins", "Black Dinner Napkins", "buffet_napkins", "fixed_1",
                default_notes="1 pack"),
    PackingItem("linen_napkins_pocket", "Linen Napkins (pocket fold)", "buffet_napkins", "per_pax"),

    # === T&C STATION ===
    PackingItem("tc_teacups", "Teacups", "tc_station", "per_pax_1.5",
                condition="has_tc"),
    PackingItem("tc_saucers", "Saucers", "tc_station", "per_pax_1.5",
                condition="has_tc"),
    PackingItem("tc_teaspoons", "Teaspoons", "tc_station", "per_pax_1.5",
                condition="has_tc", default_notes="Prepped in pocket folds"),
    PackingItem("tc_urn_stands", "Urn Stands", "tc_station", "per_station",
                condition="has_tc"),
    PackingItem("tc_urns", "Urns", "tc_station", "per_station",
                condition="has_tc"),
    PackingItem("tc_coffee_beans_dish", "Butter Dish (Coffee Beans)", "tc_station", "per_station",
                condition="has_tc", default_notes="Prep coffee beans in container"),
    PackingItem("tc_tea_leaves_dish", "Butter Dish (Tea Leaves)", "tc_station", "per_station",
                condition="has_tc", default_notes="Prep tea leaves in container"),
    PackingItem("tc_tea_box", "Tea Box", "tc_station", "per_station",
                condition="has_tc", default_notes="Ensure full - mixed variety"),
    PackingItem("tc_sugar_stands", "Gold Sugar Stands", "tc_station", "per_station",
                condition="has_tc", default_notes="Ensure full - raw, white, equal"),
    PackingItem("tc_underliner_flatfold", "Underliner Plates (with flatfold)", "tc_station", "manual",
                condition="has_tc"),
    PackingItem("tc_label_holders", "Small Acrylic Label Holders", "tc_station", "manual",
                condition="has_tc", default_notes="Hot water, coffee, milks"),

    # === WATER STATION ===
    PackingItem("water_non_alc_glasses", "Non-Alc Glasses", "water_station", "per_pax"),
    PackingItem("water_underliner", "Underliner Plates (with flatfold)", "water_station", "manual"),
]


# ============ PLENARY ITEMS ============

PLENARY_ITEMS: List[PackingItem] = [
    # === LINEN ===
    PackingItem("plenary_black_fitted", "Black Fitted Cloths", "plenary_linen", "per_table"),
    PackingItem("plenary_white_fitted", "White Fitted Cloths", "plenary_linen", "per_table"),
    PackingItem("plenary_naked_trestles", "Naked Trestles", "plenary_linen", "manual",
                default_notes="No linen required"),

    # === PLENARY PREP ===
    PackingItem("plenary_mint_bowls", "Mint Bowls", "plenary_prep", "per_table"),
    PackingItem("plenary_pens", "Pens", "plenary_prep", "per_pax"),
    PackingItem("plenary_a5_pads", "A5 Pads", "plenary_prep", "per_pax"),
    PackingItem("plenary_coasters", "Coasters", "plenary_prep", "per_pax"),
    PackingItem("plenary_water_glass", "Water Glass", "plenary_prep", "per_pax"),
    PackingItem("plenary_underliner", "Underliners", "plenary_prep", "per_table",
                default_notes="With white flatfold"),
    PackingItem("plenary_water_jugs", "Silver Water Jugs", "plenary_prep", "per_table"),
]


# ============ CATEGORY DEFINITIONS ============

# Plated categories
PLATED_CATEGORY_ORDER = ["linen", "table_set", "kitchen", "tc", "service", "bar_boh", "bar_foh", "canape"]
PLATED_CATEGORY_LABELS = {
    "linen": "Linen",
    "table_set": "Table Set",
    "kitchen": "Kitchen",
    "tc": "Tea & Coffee",
    "service": "Other Service",
    "bar_boh": "Bar - BOH (Dispense)",
    "bar_foh": "Bar - FOH (If Required)",
    "canape": "Canapé Service",
}

# Buffet categories
BUFFET_CATEGORY_ORDER = ["buffet_setup", "buffet_napkins", "tc_station", "water_station"]
BUFFET_CATEGORY_LABELS = {
    "buffet_setup": "Buffet Setup",
    "buffet_napkins": "Napkins",
    "tc_station": "Tea & Coffee Station",
    "water_station": "Water Station",
}

# Plenary categories
PLENARY_CATEGORY_ORDER = ["plenary_linen", "plenary_prep"]
PLENARY_CATEGORY_LABELS = {
    "plenary_linen": "Linen",
    "plenary_prep": "Plenary Prep",
}


def get_category_order(event_type: str) -> List[str]:
    """Get category order for event type."""
    if event_type == "plated":
        return PLATED_CATEGORY_ORDER
    elif event_type == "buffet":
        return BUFFET_CATEGORY_ORDER
    elif event_type == "plenary":
        return PLENARY_CATEGORY_ORDER
    return []


def get_category_labels(event_type: str) -> Dict[str, str]:
    """Get category labels for event type."""
    if event_type == "plated":
        return PLATED_CATEGORY_LABELS
    elif event_type == "buffet":
        return BUFFET_CATEGORY_LABELS
    elif event_type == "plenary":
        return PLENARY_CATEGORY_LABELS
    return {}


def get_items_for_event_type(event_type: str) -> List[PackingItem]:
    """Get items list for event type."""
    if event_type == "plated":
        return PLATED_ITEMS
    elif event_type == "buffet":
        return BUFFET_ITEMS
    elif event_type == "plenary":
        return PLENARY_ITEMS
    return []


# ============ PACKING LIST GENERATION ============

def generate_packing_list(
    event_name: str,
    event_date: Optional[date],
    location: str,
    pax: int,
    tables: int,
    event_type: str = "plated",
    sub_type: str = "",
    # Plated options
    courses: int = 2,
    has_tc: bool = False,
    has_foh_bar: bool = False,
    has_canapes: bool = False,
    napkin_color: str = "black",
    underliner_color: str = "white",
    round_color: str = "black",
    # Buffet options
    buffet_setups: int = 1,
    hot_items: int = 0,
    cold_items: int = 0,
    tc_stations: int = 1,
    water_stations: int = 1,
    riser_color: str = "white",
    # Plenary options
    trestle_count: int = 0,
    linen_style: str = "black_fitted",  # "black_fitted", "white_fitted", "naked"
) -> PackingList:
    """Generate a packing list with calculated quantities."""

    # Build options dict for condition checking
    has_entree = courses >= 2 if event_type == "plated" else False
    has_dessert = courses >= 2 if event_type == "plated" else (sub_type in ["lunch", "dinner", "lunch_at", "full_day"])

    options = {
        "has_entree": has_entree,
        "has_dessert": has_dessert,
        "has_tc": has_tc or tc_stations > 0,
        "has_foh_bar": has_foh_bar,
        "has_canapes": has_canapes,
        "buffet_setups": buffet_setups,
        "hot_items": hot_items,
        "cold_items": cold_items,
    }

    # Get items for this event type
    source_items = get_items_for_event_type(event_type)

    # Use trestle_count as tables for plenary
    effective_tables = trestle_count if event_type == "plenary" else tables

    # Use tc_stations for plenary/buffet
    effective_stations = tc_stations

    # Generate items
    items = []
    for item in source_items:
        qty = item.calculate_qty(pax, effective_tables, effective_stations, options)

        # === PLATED-SPECIFIC LOGIC ===
        if event_type == "plated":
            # Special case: Entrée fork needs 2x for 3-course (entrée + dessert)
            if item.id == "entree_fork" and courses == 3:
                qty = pax * 2

            # Handle color selection for napkins, underliners, and rounds
            if item.id == "black_napkins" and napkin_color != "black":
                qty = 0
            elif item.id == "white_napkins" and napkin_color != "white":
                qty = 0
            elif item.id == "black_underliner" and underliner_color != "black":
                qty = 0
            elif item.id == "white_underliner" and underliner_color != "white":
                qty = 0
            elif item.id == "black_rounds" and round_color != "black":
                qty = 0
            elif item.id == "white_rounds" and round_color != "white":
                qty = 0

        # === BUFFET-SPECIFIC LOGIC ===
        elif event_type == "buffet":
            # Handle riser color
            if item.id == "white_riser_sets" and riser_color != "white":
                qty = 0
            elif item.id == "black_riser_sets" and riser_color != "black":
                qty = 0

            # Napkin selection based on sub_type (dinner uses black, others use white)
            is_dinner = sub_type in ["dinner"]
            if item.id == "white_cocktail_napkins" and is_dinner:
                qty = 0
            elif item.id == "black_cocktail_napkins" and not is_dinner:
                qty = 0
            elif item.id == "white_dinner_napkins" and is_dinner:
                qty = 0
            elif item.id == "black_dinner_napkins" and not is_dinner:
                qty = 0

        # === PLENARY-SPECIFIC LOGIC ===
        elif event_type == "plenary":
            # Handle linen style
            if item.id == "plenary_black_fitted" and linen_style != "black_fitted":
                qty = 0
            elif item.id == "plenary_white_fitted" and linen_style != "white_fitted":
                qty = 0
            elif item.id == "plenary_naked_trestles" and linen_style != "naked":
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
        event_type=event_type,
        sub_type=sub_type,
        courses=courses,
        has_entree=has_entree,
        has_dessert=has_dessert,
        has_tc=has_tc,
        has_foh_bar=has_foh_bar,
        has_canapes=has_canapes,
        napkin_color=napkin_color,
        underliner_color=underliner_color,
        round_color=round_color,
        buffet_setups=buffet_setups,
        hot_items=hot_items,
        cold_items=cold_items,
        tc_stations=tc_stations,
        water_stations=water_stations,
        trestle_count=trestle_count,
        items=items,
        created_at=datetime.now().isoformat(),
        status="draft",
    )


def get_items_by_category(packing_list: PackingList) -> Dict[str, List[PackingListItem]]:
    """Group packing list items by category."""
    category_order = get_category_order(packing_list.event_type)
    result = {cat: [] for cat in category_order}
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


# Backwards compatibility - keep these for existing code
PACKING_ITEMS = PLATED_ITEMS
CATEGORY_ORDER = PLATED_CATEGORY_ORDER
CATEGORY_LABELS = PLATED_CATEGORY_LABELS
