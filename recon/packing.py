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
        """Calculate quantity based on formula and event config.

        Formulas match Excel packing sheet calculations:
        - per_pax: =SUM(B3) - one per guest
        - per_pax_1.5: =SUM(B3*1.5) - 1.5 per guest (glassware)
        - per_pax_2: =SUM(B3*2) - 2 per guest
        - per_pax_3: =SUM(B3*3) - 3 per guest (coasters)
        - pax_div_4: =ROUNDUP(B3/4,0) - 1 per 4 guests (mint bowls)
        - pax_div_5: =SUM(B3/5) - 1 per 5 guests (mints)
        - per_table: =SUM(B4) - one per table
        - per_table_2: =SUM(B4*2) - 2 per table
        - per_table_3: =SUM(B4*3) - 3 per table (underliners)
        - per_10_tables: =ROUNDUP(B4/10,0) - 1 per 10 tables
        - per_trestle: one per trestle (plenary)
        - per_buffet: =SUM(buffet_setups) - one per buffet setup
        - per_buffet_4: =4*buffet_setups - 4 per buffet (side plates)
        - per_hot_item: =SUM(hot_items) - one per hot item
        - per_cold_item: =SUM(cold_items) - one per cold item
        - hot_plus_cold: =SUM(hot+cold) - tongs, tong plates
        - hot_plus_cold_x2: =SUM(hot+cold)*2 - double tongs
        - per_chaffing_2: =2*chaffing_dishes - sternos (2 per chaffing)
        - per_tc_station: one per T&C station
        - per_tc_station_2: =2*tc_stations - urns (2 per station)
        - per_tc_station_6: =6*tc_stations - underliner plates for TC
        - per_water_station: one per water station
        - manual: user fills in quantity
        - fixed_N: fixed quantity N
        """
        # Check condition first
        if self.condition:
            if not options.get(self.condition, False):
                return 0

        buffet_setups = options.get("buffet_setups", 1)
        hot_items = options.get("hot_items", 0)
        cold_items = options.get("cold_items", 0)
        tc_stations = options.get("tc_stations", 0)
        water_stations = options.get("water_stations", 0)
        trestle_count = options.get("trestle_count", 0)

        # Calculate based on formula
        if self.formula == "per_pax":
            return pax
        elif self.formula == "per_pax_1.5":
            return math.ceil(pax * 1.5)
        elif self.formula == "per_pax_2":
            return pax * 2
        elif self.formula == "per_pax_3":
            return pax * 3
        elif self.formula == "pax_div_4":
            return math.ceil(pax / 4)
        elif self.formula == "pax_div_5":
            return math.ceil(pax / 5)
        elif self.formula == "per_table":
            return tables
        elif self.formula == "per_table_2":
            return tables * 2
        elif self.formula == "per_table_3":
            return tables * 3
        elif self.formula == "per_10_tables":
            return math.ceil(tables / 10)
        elif self.formula == "per_trestle":
            return trestle_count
        elif self.formula == "per_buffet":
            return buffet_setups
        elif self.formula == "per_buffet_4":
            return buffet_setups * 4
        elif self.formula == "per_hot_item":
            return hot_items
        elif self.formula == "per_cold_item":
            return cold_items
        elif self.formula == "hot_plus_cold":
            return hot_items + cold_items
        elif self.formula == "hot_plus_cold_x2":
            return (hot_items + cold_items) * 2
        elif self.formula == "per_chaffing_2":
            return hot_items * 2  # 2 sternos per chaffing dish
        elif self.formula == "per_station":
            return stations
        elif self.formula == "per_tc_station":
            return tc_stations
        elif self.formula == "per_tc_station_2":
            return tc_stations * 2
        elif self.formula == "per_tc_station_6":
            return tc_stations * 6
        elif self.formula == "per_water_station":
            return water_stations
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
class MealSection:
    """A meal section within a multi-meal buffet (e.g., Morning Tea, Lunch, Afternoon Tea)."""
    name: str  # e.g., "Morning Tea Buffet", "Lunch Buffet"
    section_id: str  # e.g., "morning_tea", "lunch", "afternoon_tea"
    buffet_setups: int = 1
    hot_items: int = 0
    cold_items: int = 0
    dessert_items: int = 0
    items: List[PackingListItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MealSection":
        items = [PackingListItem(**item) for item in data.pop("items", [])]
        return cls(**data, items=items)


# Define which sub-types have multiple meal sections
MULTI_MEAL_CONFIGS = {
    "mt_lunch_at": [
        {"section_id": "morning_tea", "name": "Morning Tea Buffet"},
        {"section_id": "lunch", "name": "Lunch Buffet"},
        {"section_id": "afternoon_tea", "name": "Afternoon Tea Buffet"},
    ],
    "morning_tea_lunch": [
        {"section_id": "morning_tea", "name": "Morning Tea Buffet"},
        {"section_id": "lunch", "name": "Lunch Buffet"},
    ],
    "lunch_afternoon_tea": [
        {"section_id": "lunch", "name": "Lunch Buffet"},
        {"section_id": "afternoon_tea", "name": "Afternoon Tea Buffet"},
    ],
    "breakfast_mt_lunch": [
        {"section_id": "breakfast", "name": "Breakfast Buffet"},
        {"section_id": "morning_tea", "name": "Morning Tea Buffet"},
        {"section_id": "lunch", "name": "Lunch Buffet"},
    ],
}


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

    # Items (for single-meal events or shared items like T&C/Water stations)
    items: List[PackingListItem] = field(default_factory=list)

    # Meal sections (for multi-meal buffets like MT+Lunch+AT)
    meal_sections: List[MealSection] = field(default_factory=list)

    # Metadata
    created_at: str = ""
    status: str = "draft"

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        if self.event_date:
            result["event_date"] = self.event_date.isoformat()
        # Convert meal_sections
        result["meal_sections"] = [ms.to_dict() for ms in self.meal_sections]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PackingList":
        if data.get("event_date"):
            data["event_date"] = date.fromisoformat(data["event_date"])
        items = [PackingListItem(**item) for item in data.pop("items", [])]
        meal_sections = [MealSection.from_dict(ms) for ms in data.pop("meal_sections", [])]
        return cls(**data, items=items, meal_sections=meal_sections)


# ============ EVENT TYPE DEFINITIONS ============

EVENT_TYPES = {
    "plated": "Plated Dinner",
    "buffet": "Buffet",
    "plenary": "Plenary / Boardroom",
}

BUFFET_SUB_TYPES = {
    # Breakfast options
    "buffet_breakfast": "Buffet Breakfast",
    "pancake_station": "Pancake Station",
    "omelette_station": "Omelette Station",
    "eggs_benedict": "Eggs Benedict",
    "breakfast_mt_lunch": "Breakfast, MT & Lunch",
    # Morning tea options
    "buffet_morning_tea": "Buffet Morning Tea",
    "morning_tea_lunch": "Morning Tea and Lunch",
    "mt_lunch_at": "Buffet MT, Lunch & Afternoon Tea",
    # Lunch options
    "buffet_lunch": "Buffet Lunch",
    "lunch_afternoon_tea": "Lunch and Afternoon Tea",
    # Afternoon tea
    "buffet_afternoon_tea": "Buffet Afternoon Tea",
    # Dinner options
    "buffet_dinner": "Buffet Dinner",
    "breakfast_to_dinner": "Buffet - Breakfast to Dinner",
    "bbq_buffet": "BBQ Buffet",
    "gaming_seafood": "Gaming Seafood Buffet",
    # Food stations
    "bao_station": "Bao Station",
    "pasta_station": "Pasta Station",
    "taco_station": "Taco Station",
    "hot_food_station": "Hot Food Station",
    "cheese_station": "Cheese Station",
    "smoker_station": "Smoker Station",
    "carving_station": "Carving Station",
    "paella_station": "Paella Station",
    "poke_station": "Poke Station",
    "platter_station": "Platter Station",
    # Other
    "canape": "Canapé",
    "dessert": "Dessert",
    "dietary": "Dietary",
    "smoothie_station": "Smoothie Station",
    "juice_buffet": "Juice Buffet",
    "tc_station": "T&C Station",
    "coffee_cart": "Coffee Cart",
    # Level 7 Cocktail
    "level7_cocktail_250": "Level 7 Cocktail 250 pax",
    "level7_cocktail_500": "Level 7 Cocktail 500 pax",
    "level7_cocktail_1000": "Level 7 Cocktail 1000 pax",
}

PLENARY_SUB_TYPES = {
    "boardroom_plenary": "Boardroom - Plenary",
    "boardroom_executive": "Boardroom - Executive",
    "welcome_elevate": "Welcome Elevate",
    "transformation": "Transformation",
    "fb_onboarding": "F+B Onboarding",
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
# Formulas based on Excel: Master Packing Sheets- Buffets (1).xlsx

BUFFET_ITEMS: List[PackingItem] = [
    # === BUFFET SETUP ===
    # Underliner Plates: =SUM(B3) - per pax
    PackingItem("buffet_underliner", "Underliner Plates", "buffet_setup", "per_pax"),
    # Entrée Plate: =SUM(B3) - per pax
    PackingItem("buffet_entree_plate", "Entrée Plate", "buffet_setup", "per_pax"),
    # Entrée Fork: =SUM(B3) - per pax
    PackingItem("buffet_entree_fork", "Entrée Fork", "buffet_setup", "per_pax",
                default_notes="Prepped in pocket fold or silver basket"),
    # Entrée Knife: =SUM(B3) - per pax
    PackingItem("buffet_entree_knife", "Entrée Knife", "buffet_setup", "per_pax",
                default_notes="Prepped in pocket fold or silver basket"),
    # Dessert Spoon: =SUM(B3) - per pax, when dessert
    PackingItem("buffet_dessert_spoon", "Dessert Spoon", "buffet_setup", "per_pax",
                condition="has_dessert"),
    # Tongs: =SUM(hot_items, cold_items) - one per menu item
    PackingItem("buffet_tongs", "Tongs", "buffet_setup", "hot_plus_cold"),
    # Serving Spoon: manual (varies by event)
    PackingItem("buffet_serving_spoon", "Serving Spoon", "buffet_setup", "manual"),
    # Tong Plates: =SUM(tongs) - same as tongs
    PackingItem("buffet_tong_plates", "Tong Plates", "buffet_setup", "hot_plus_cold"),
    # Side Plates: =4*buffet_setups - 4 per buffet for cocktail napkins
    PackingItem("buffet_side_plates", "Side Plates", "buffet_setup", "per_buffet_4",
                default_notes="For cocktail napkins"),
    # White Riser Sets: =SUM(cold_items) - 1 set per cold item
    PackingItem("white_riser_sets", "White Riser Sets", "buffet_setup", "per_cold_item",
                default_notes="Small & medium for every cold item"),
    # Black Riser Sets: =SUM(cold_items) - 1 set per cold item
    PackingItem("black_riser_sets", "Black Riser Sets", "buffet_setup", "per_cold_item",
                default_notes="Small & medium for every cold item"),
    # Chaffing Dish: =SUM(hot_items) - 1 per hot item
    PackingItem("chaffing_dish", "Chaffing Dish", "buffet_setup", "per_hot_item",
                default_notes="Rectangular unless otherwise stated"),
    # Sternos: =2*chaffing_dishes - 2 per chaffing dish
    PackingItem("sternos", "Sternos", "buffet_setup", "per_chaffing_2",
                default_notes="2 per chaffing dish"),
    # Sterno Holders: =SUM(sternos) - same as sternos
    PackingItem("sterno_holders", "Sterno Holders", "buffet_setup", "per_chaffing_2"),
    # Rectangle Plate: =2*pax for cutlery pocket folds (lunch)
    PackingItem("rectangle_plate", "Rectangle Plate", "buffet_setup", "per_pax_2",
                default_notes="For cutlery pocket folds"),
    # Linen Napkins: =SUM(rectangle_plates) - for pocket fold
    PackingItem("linen_napkins_pocketfold", "Linen Napkins (pocket fold)", "buffet_setup", "per_pax_2",
                default_notes="For pocket fold"),
    # Silver Baskets: manual
    PackingItem("silver_baskets", "Silver Baskets", "buffet_setup", "manual",
                default_notes="For cutlery display"),
    # Salt & Pepper: =SUM(buffet_setups) - 1 per buffet
    PackingItem("salt_pepper_buffet", "Salt & Pepper Sets", "buffet_setup", "per_buffet"),
    # A4 Menu Holders: =SUM(buffet_setups) - 1 per buffet
    PackingItem("a4_menu_holders", "A4 Acrylic Menu Holders", "buffet_setup", "per_buffet"),
    # Small Label Holders: =SUM(hot+cold)*buffet_setups - per item per buffet
    PackingItem("small_label_holders", "Small Acrylic Label Holders", "buffet_setup", "hot_plus_cold",
                default_notes="For menu item labels"),

    # === NAPKINS ===
    # Cocktail Napkins: =SUM(buffet_setups) - 1 pack per buffet
    PackingItem("white_cocktail_napkins", "White Cocktail Napkins", "buffet_napkins", "per_buffet",
                default_notes="1 pack per buffet"),
    PackingItem("black_cocktail_napkins", "Black Cocktail Napkins", "buffet_napkins", "per_buffet",
                default_notes="1 pack per buffet"),
    PackingItem("white_dinner_napkins", "White Dinner Napkins", "buffet_napkins", "fixed_1",
                default_notes="1 pack"),
    PackingItem("black_dinner_napkins", "Black Dinner Napkins", "buffet_napkins", "fixed_1",
                default_notes="1 pack"),
    PackingItem("linen_napkins_pocket", "Linen Napkins (pocket fold)", "buffet_napkins", "per_pax"),

    # === T&C STATION ===
    # Teacups: =SUM(B3) or 1.5x pax - per pax (adjust up for large events)
    PackingItem("tc_teacups", "Teacups", "tc_station", "per_pax",
                condition="has_tc"),
    # Saucers: =SUM(teacups) - same as teacups
    PackingItem("tc_saucers", "Saucers", "tc_station", "per_pax",
                condition="has_tc"),
    # Teaspoons: =SUM(teacups) - same as teacups
    PackingItem("tc_teaspoons", "Teaspoons", "tc_station", "per_pax",
                condition="has_tc", default_notes="Prepped in pocket folds"),
    # Urns: =SUM(tc_stations*2) - 2 per station
    PackingItem("tc_urns", "Urns", "tc_station", "per_tc_station_2",
                condition="has_tc"),
    # Urn Stands: =SUM(tc_stations*2) - 2 per station
    PackingItem("tc_urn_stands", "Urn Stands", "tc_station", "per_tc_station_2",
                condition="has_tc"),
    # Butter Dish (Coffee Beans): =1*tc_stations - 1 per station
    PackingItem("tc_coffee_beans_dish", "Butter Dish (Coffee Beans)", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="Prep coffee beans in container"),
    # Butter Dish (Tea Leaves): =1*tc_stations - 1 per station
    PackingItem("tc_tea_leaves_dish", "Butter Dish (Tea Leaves)", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="Prep tea leaves in container"),
    # Tea Box: =1*tc_stations - 1 per station
    PackingItem("tc_tea_box", "Tea Box", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="Ensure full - mixed variety"),
    # Gold Sugar Stands: per station
    PackingItem("tc_sugar_stands", "Gold Sugar Stands", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="Ensure full - raw, white, equal"),
    # Sternos: per station
    PackingItem("tc_sternos", "Sternos", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="Prep in sterno holders"),
    # Sterno Holders: same as sternos
    PackingItem("tc_sterno_holders", "Sterno Holders", "tc_station", "per_tc_station",
                condition="has_tc"),
    # Underliner Plates: =6*tc_stations - 6 per station
    PackingItem("tc_underliner_flatfold", "Underliner Plates (with flatfold)", "tc_station", "per_tc_station_6",
                condition="has_tc"),
    # Small Acrylic Label Holders: =SUM(underliners) - for hot water, coffee, milks
    PackingItem("tc_label_holders", "Small Acrylic Label Holders", "tc_station", "per_tc_station_6",
                condition="has_tc", default_notes="Hot water, coffee, milks"),
    # Cocktail Napkins: 1 pack per station
    PackingItem("tc_cocktail_napkins", "Cocktail Napkins", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="1 pack"),
    # Side Plates: 4 per station for napkins
    PackingItem("tc_side_plates", "Side Plates", "tc_station", "per_tc_station",
                condition="has_tc", default_notes="For cocktail napkins"),

    # === WATER STATION ===
    # Non-Alc Glasses: =SUM(B3) - per pax
    PackingItem("water_non_alc_glasses", "Non-Alc Glasses", "water_station", "per_pax"),
    # Underliner Plates: manual (varies by setup)
    PackingItem("water_underliner", "Underliner Plates (with flatfold)", "water_station", "manual"),
]


# ============ PLENARY ITEMS ============
# Formulas based on Excel: Master Packing Sheet Plentary.xlsx

PLENARY_ITEMS: List[PackingItem] = [
    # === LINEN ===
    # Black Fitted Cloths: per trestle
    PackingItem("plenary_black_fitted", "Black Fitted Cloths", "plenary_linen", "per_trestle"),
    # White Fitted Cloths: per trestle
    PackingItem("plenary_white_fitted", "White Fitted Cloths", "plenary_linen", "per_trestle"),
    # Naked Trestles: manual (no linen)
    PackingItem("plenary_naked_trestles", "Naked Trestles", "plenary_linen", "per_trestle",
                default_notes="No linen required"),

    # === PLENARY PREP ===
    # Mint Bowls: =ROUNDUP(B3/4,0) for executive, or per trestle for standard plenary
    PackingItem("plenary_mint_bowls", "Mint Bowls", "plenary_prep", "pax_div_4"),
    # Pens: =SUM(B3) - per pax
    PackingItem("plenary_pens", "Pens", "plenary_prep", "per_pax"),
    # A5 Pads: =SUM(B3) - per pax
    PackingItem("plenary_a5_pads", "A5 Pads", "plenary_prep", "per_pax"),
    # Coasters: =SUM(B3) - per pax (executive uses 3x)
    PackingItem("plenary_coasters", "Coasters", "plenary_prep", "per_pax"),
    # Water Glass: =SUM(B3) - per pax
    PackingItem("plenary_water_glass", "Water Glass", "plenary_prep", "per_pax"),
    # Underliners: per trestle
    PackingItem("plenary_underliner", "Underliners", "plenary_prep", "per_trestle",
                default_notes="With white flatfold"),
    # Silver Water Jugs: per trestle
    PackingItem("plenary_water_jugs", "Silver Water Jugs", "plenary_prep", "per_trestle"),
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

# Buffet categories (for single-meal buffets)
BUFFET_CATEGORY_ORDER = ["buffet_setup", "buffet_napkins", "tc_station", "water_station"]
BUFFET_CATEGORY_LABELS = {
    "buffet_setup": "Buffet Setup",
    "buffet_napkins": "Napkins",
    "tc_station": "Tea & Coffee Station",
    "water_station": "Water Station",
}

# Categories for meal sections (per-meal items)
MEAL_SECTION_CATEGORIES = ["buffet_setup", "buffet_napkins"]
# Categories for shared items (T&C, Water - at end of packing list)
SHARED_CATEGORIES = ["tc_station", "water_station"]

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
    # Multi-meal buffet sections (list of dicts with section_id, name, buffet_setups, hot_items, cold_items, dessert_items)
    meal_sections_input: Optional[List[Dict[str, Any]]] = None,
    # Plenary options
    trestle_count: int = 0,
    linen_style: str = "black_fitted",  # "black_fitted", "white_fitted", "naked"
) -> PackingList:
    """Generate a packing list with calculated quantities.

    For multi-meal buffets (e.g., MT + Lunch + AT), pass meal_sections_input with
    setup values for each meal. Shared items (T&C, Water stations) go in the main items list.
    """

    # Build options dict for condition checking
    has_entree = courses >= 2 if event_type == "plated" else False
    has_dessert = courses >= 2 if event_type == "plated" else (sub_type in ["buffet_lunch", "buffet_dinner", "lunch_afternoon_tea", "mt_lunch_at"])

    # Check if this is a multi-meal buffet
    is_multi_meal = event_type == "buffet" and sub_type in MULTI_MEAL_CONFIGS

    # Get items for this event type
    source_items = get_items_for_event_type(event_type)

    # Use trestle_count as tables for plenary
    effective_tables = trestle_count if event_type == "plenary" else tables

    items = []
    meal_sections = []

    if is_multi_meal and meal_sections_input:
        # === MULTI-MEAL BUFFET ===
        # Generate items for each meal section
        for section_input in meal_sections_input:
            section_id = section_input.get("section_id", "")
            section_name = section_input.get("name", section_id.replace("_", " ").title())
            section_buffet_setups = section_input.get("buffet_setups", 1)
            section_hot_items = section_input.get("hot_items", 0)
            section_cold_items = section_input.get("cold_items", 0)
            section_dessert_items = section_input.get("dessert_items", 0)

            # Build section-specific options
            section_options = {
                "has_entree": True,
                "has_dessert": section_id in ["lunch", "afternoon_tea", "dinner"] or section_dessert_items > 0,
                "has_tc": tc_stations > 0,
                "buffet_setups": section_buffet_setups,
                "hot_items": section_hot_items,
                "cold_items": section_cold_items + section_dessert_items,
                "tc_stations": tc_stations,
                "water_stations": water_stations,
                "trestle_count": 0,
            }

            section_items = []
            for item in source_items:
                # Only include meal-section categories (buffet_setup, buffet_napkins)
                if item.category not in MEAL_SECTION_CATEGORIES:
                    continue

                qty = item.calculate_qty(pax, effective_tables, tc_stations, section_options)

                # Handle riser color
                if item.id == "white_riser_sets" and riser_color != "white":
                    qty = 0
                elif item.id == "black_riser_sets" and riser_color != "black":
                    qty = 0

                # Napkin selection (dinner uses black, others use white)
                is_dinner_section = section_id == "dinner"
                if item.id == "white_cocktail_napkins" and is_dinner_section:
                    qty = 0
                elif item.id == "black_cocktail_napkins" and not is_dinner_section:
                    qty = 0
                elif item.id == "white_dinner_napkins" and is_dinner_section:
                    qty = 0
                elif item.id == "black_dinner_napkins" and not is_dinner_section:
                    qty = 0

                section_items.append(PackingListItem(
                    item_id=item.id,
                    name=item.name,
                    category=item.category,
                    suggested_qty=qty,
                    final_qty=qty,
                    packed=False,
                    notes=item.default_notes,
                ))

            meal_sections.append(MealSection(
                name=section_name,
                section_id=section_id,
                buffet_setups=section_buffet_setups,
                hot_items=section_hot_items,
                cold_items=section_cold_items,
                dessert_items=section_dessert_items,
                items=section_items,
            ))

        # Generate shared items (T&C Station, Water Station)
        shared_options = {
            "has_entree": False,
            "has_dessert": False,
            "has_tc": tc_stations > 0,
            "buffet_setups": buffet_setups,
            "hot_items": 0,
            "cold_items": 0,
            "tc_stations": tc_stations,
            "water_stations": water_stations,
            "trestle_count": 0,
        }

        for item in source_items:
            if item.category not in SHARED_CATEGORIES:
                continue

            qty = item.calculate_qty(pax, effective_tables, tc_stations, shared_options)

            items.append(PackingListItem(
                item_id=item.id,
                name=item.name,
                category=item.category,
                suggested_qty=qty,
                final_qty=qty,
                packed=False,
                notes=item.default_notes,
            ))

    else:
        # === SINGLE-MEAL BUFFET OR OTHER EVENT TYPES ===
        options = {
            "has_entree": has_entree,
            "has_dessert": has_dessert,
            "has_tc": has_tc or tc_stations > 0,
            "has_foh_bar": has_foh_bar,
            "has_canapes": has_canapes,
            "buffet_setups": buffet_setups,
            "hot_items": hot_items,
            "cold_items": cold_items,
            "tc_stations": tc_stations,
            "water_stations": water_stations,
            "trestle_count": trestle_count,
        }

        for item in source_items:
            qty = item.calculate_qty(pax, effective_tables, tc_stations, options)

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
                is_dinner = sub_type in ["buffet_dinner"]
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
        meal_sections=meal_sections,
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
