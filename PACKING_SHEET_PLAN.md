# Packing Sheet / Pick List Feature Plan

## Current State Analysis

### Existing Excel Structure
The current Excel workbook has **8 event templates**:
1. Breakfast Plated
2. 2 Course Plated
3. 2 Course + Canape
4. 2 Course Plated (Preset T&C)
5. 3 Course Plated
6. 3 Course Plated + Canape
7. 3 Course Plated (Preset T&C)
8. Menu Tasting

### Input Variables Used
- **Guest Count (pax)** - drives most item quantities
- **Table Count** - drives tablecloths, centerpieces, per-table items
- **Course Configuration** - ENTRÉE/MAIN and MAIN/DESSERT toggles

### Item Categories
| Category | Examples | Quantity Formula |
|----------|----------|------------------|
| Linen | Napkins, Rounds (tablecloths) | 1 per pax, 1 per table |
| Table Set | Cutlery, glasses, plates | 1-2 per pax |
| Kitchen | Bread baskets, butter dishes | 2 per table |
| T&C | Tea/coffee service trays | Fixed (e.g., 5) |
| Other Service | Jack trays | 1 per 10 tables |
| BOH Bar | Bar glasses | 1.5x per pax |
| FOH Bar | Front bar glasses (if needed) | 1.5x per pax |

### Current Pain Points
1. Multiple Excel templates - hard to maintain
2. Event types don't always fit neat categories (conferences, cocktails, etc.)
3. Manual formula entry prone to errors
4. No connection to EO data
5. Physical checklist (PACKED Y/N) not digital

---

## Proposed Solution: Hybrid Pick List System

### Philosophy
Rather than trying to auto-generate a perfect packing list from EO data, create a **semi-automated pick list** where:
1. User inputs key variables (pax, tables, event type)
2. System suggests items and quantities based on templates
3. User can add/remove items and adjust quantities
4. Generate printable/exportable packing checklist

### Why This Approach?
- **EO parsing isn't perfect** - and doesn't need to be for this to work
- **Flexibility** - handles non-standard events
- **Staff input** - managers know special requirements
- **Incremental** - can add more automation later as EO parsing improves

---

## Feature Design

### Page Structure: "Packing Lists"

```
┌─────────────────────────────────────────────────────────────┐
│ 📦 Packing List Generator                                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 1: Event Details                                      │
│  ┌─────────────────┬─────────────────┬──────────────────┐  │
│  │ Event Name      │ Event Date      │ Location         │  │
│  │ [____________] │ [__/__/____]   │ [Brisbane BB ▼]  │  │
│  └─────────────────┴─────────────────┴──────────────────┘  │
│                                                             │
│  Step 2: Event Configuration                                │
│  ┌─────────────────┬─────────────────┬──────────────────┐  │
│  │ Guest Count     │ Table Count     │ Event Type       │  │
│  │ [  500  ]       │ [  50   ]       │ [3 Course ▼]     │  │
│  └─────────────────┴─────────────────┴──────────────────┘  │
│                                                             │
│  ☑ Has Entrée/Main   ☑ Has Main/Dessert   ☐ Preset T&C    │
│  ☐ Canapes           ☐ FOH Bar Required                    │
│                                                             │
│  [Generate Suggested List]                                  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 3: Review & Adjust Items                              │
│                                                             │
│  ▼ LINEN (4 items)                                         │
│  ┌──────────────────┬─────────┬───────┬─────────────────┐  │
│  │ Item             │ Suggest │ Final │ Notes           │  │
│  ├──────────────────┼─────────┼───────┼─────────────────┤  │
│  │ ☑ Black Napkins  │   500   │ [500] │ Book folded     │  │
│  │ ☐ White Napkins  │    0    │ [ 0 ] │ Book folded     │  │
│  │ ☑ Black Rounds   │   50    │ [50 ] │                 │  │
│  │ ☐ White Rounds   │    0    │ [ 0 ] │                 │  │
│  └──────────────────┴─────────┴───────┴─────────────────┘  │
│                                                             │
│  ▼ TABLE SET (12 items)                                    │
│  ▼ KITCHEN (3 items)                                       │
│  ▼ BAR - BOH (5 items)                                     │
│  ▼ BAR - FOH (5 items) [collapsed - not required]          │
│                                                             │
│  [+ Add Custom Item]                                        │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Step 4: Export                                             │
│  [📄 Download PDF] [📊 Download Excel] [💾 Save Draft]      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Data Model

### Item Templates (items.json or database)

```python
@dataclass
class PackingItem:
    id: str                    # e.g., "black_napkins"
    name: str                  # "Black Napkins"
    category: str              # "linen", "table_set", "kitchen", "bar_boh", "bar_foh"
    unit: str                  # "each", "set", "dozen"
    default_notes: str         # "Book folded"

    # Quantity calculation
    base_multiplier: str       # "per_pax", "per_table", "fixed", "per_10_tables"
    multiplier_value: float    # 1.0, 1.5, 2.0, etc.

    # Conditional inclusion
    requires: List[str]        # ["has_entree_main"] - only include if these are true


@dataclass
class EventTemplate:
    id: str                    # "3_course_plated"
    name: str                  # "3 Course Plated"
    items: List[str]           # Item IDs to include by default
    default_toggles: Dict      # {"has_entree_main": True, "has_dessert": True}


@dataclass
class PackingList:
    id: str
    event_name: str
    event_date: date
    location: str
    pax: int
    tables: int
    template_id: str
    items: List[PackingListItem]
    created_at: datetime
    created_by: str
    status: str               # "draft", "finalized", "packed"


@dataclass
class PackingListItem:
    item_id: str
    included: bool
    suggested_qty: int
    final_qty: int
    packed: bool
    notes: str
```

---

## Implementation Phases

### Phase 1: Plated Dinner Templates (MVP)
**Goal**: Working packing list generator for the 8 plated templates

**Scope - 8 Templates:**
1. Breakfast Plated
2. 2 Course Plated
3. 2 Course + Canape
4. 2 Course Plated (Preset T&C)
5. 3 Course Plated
6. 3 Course Plated + Canape
7. 3 Course Plated (Preset T&C)
8. Menu Tasting

**Implementation:**

1. **Create data model** (`recon/packing.py`)
   - PackingItem, EventTemplate, PackingList dataclasses
   - Quantity calculation functions
   - Load/save functions (JSON storage)

2. **Build item database** (`packing_data.json`)
   - All items from plated Excel with formulas
   - 8 event type templates with default items

3. **Streamlit page** (add to navigation)
   - **Step 1**: Event details (name, date, location)
   - **Step 2**: Configuration (pax, tables, template, toggles)
   - **Step 3**: Review items with adjustable quantities
   - **Step 4**: Export (Excel matching current format)

4. **Excel export** matching current template style:
   ```
   EVENT NAME:         [name]
   EVENT DATE:         [date]
   GUEST COUNT:        [pax]
   TABLE COUNT:        [tables]

   Linen Count         QUANTITY    PACKED (Y/N)    NOTES
   Black Napkins       500                         Book folded
   ...

   Table Set           QUANTITY    PACKED (Y/N)    NOTES
   Side Plate          500
   ...
   ```

**Deliverable**: Manager can generate a printable packing checklist that matches the existing Excel format

---

### Phase 2: Enhanced UX
**Goal**: Make it easier and faster to use

1. **Collapsible category sections** - expand/collapse item groups
2. **Quick presets** - "Standard dinner service" button fills common items
3. **Linen color picker** - toggle black/white napkins and rounds
4. **Running totals** - show item counts per category
5. **Draft saving** - save in-progress lists, resume later
6. **PDF export** - printable checklist format

---

### Phase 3: EO Integration (Optional)
**Goal**: Pre-fill from Event Order when available

1. **Extract from EO**:
   - Event name, date, location
   - Pax count (from day delegate package or schedule GTD)
   - Menu type hints (breakfast, lunch, dinner based on times)
   - Beverage service (bar required?)

2. **Smart suggestions**:
   - If EO has "3 course" menu items → suggest 3 Course template
   - If EO has canapes → enable canape items
   - If EO has beverage package → suggest FOH bar

3. **Workflow integration**:
   - Button on reconciliation page: "Generate Packing List for this EO"

---

### Phase 4: Advanced Features (Future)
- **Packed status tracking** - check items as packed, sync across users
- **Inventory integration** - warn if requesting more than available stock
- **History & analytics** - what items are most commonly adjusted?
- **Multi-day events** - aggregate packing across event days
- **Print labels** - generate labels for packed boxes

---

## Item Database (Initial)

Based on the Excel analysis, here are the core items:

### Linen
| Item | Formula | Notes |
|------|---------|-------|
| Black Napkins | 1 × pax | Book folded |
| White Napkins | 1 × pax | Book folded |
| Black Rounds | 1 × tables | Tablecloths |
| White Rounds | 1 × tables | Tablecloths |

### Table Set
| Item | Formula | Conditional |
|------|---------|-------------|
| Side Plate | 1 × pax | Always |
| Entrée Fork | 1 × pax | If has_entree_main OR has_main_dessert |
| Entrée Knife | 2 × pax | If has_entree_main (includes bread knife) |
| Main Fork | 1 × pax | If has_entree_main OR has_main_dessert |
| Main Knife | 1 × pax | If has_entree_main OR has_main_dessert |
| Dessert Spoon | 1 × pax | If has_main_dessert |
| Water Glass | 1 × pax | Always |
| Wine Glass | 1 × pax | Always |
| Tea Cup | 1 × pax | If preset_tc |
| Saucer | 1 × pax | If preset_tc |
| Teaspoon | 1 × pax | If preset_tc |
| Underliner Plate | 3 × tables | Same color as napkins |
| Table Numbers | 1 × tables | |
| Menu Holders | 1 × tables | |
| Salt & Pepper | 1 × tables | 1 set per table |

### Kitchen
| Item | Formula | Notes |
|------|---------|-------|
| Bread Basket | 2 × tables | With linen napkin |
| Butter Dishes | 2 × tables | Match bread baskets |

### T&C Service
| Item | Formula | Notes |
|------|---------|-------|
| Service Trays | 5 (fixed) | Saucers, cups, teaspoons |
| T&C Center | 1 × tables | If preset_tc |

### Other Service
| Item | Formula | Notes |
|------|---------|-------|
| Jack Trays | tables ÷ 10 | |
| Jack Tray Legs | match jack trays | |
| Jack Tray Linen | match jack trays | Square 224x224 |

### Bar - BOH (Back of House)
| Item | Formula | Notes |
|------|---------|-------|
| Wine Glass | 1.5 × pax | |
| Champagne Glass | 1.5 × pax | |
| Beer Glass | 1.5 × pax | |
| Rocks Glass | 1.5 × pax | |
| Non-Alc Glass | 1.5 × pax | |

### Bar - FOH (Front of House)
Same as BOH, only included if `foh_bar_required = True`

---

## Decisions Made

1. **Storage**: JSON files (simple, sufficient for now)

2. **User access**: Managers generate reports for floor staff

3. **Print format**: Match current Excel template style - simple, readable checklist

4. **Event types**:
   - **Phase 1**: 8 plated templates only (Breakfast, 2/3 Course variations)
   - **Phase 2+**: 36 buffet templates (more complex, add later)

5. **Scope**: Get plated working correctly first, establish the formula, then expand

---

## Files to Create

| File | Purpose |
|------|---------|
| `recon/packing.py` | Data models and business logic |
| `packing_items.json` | Item database (name, category, formula) |
| `packing_templates.json` | Event type templates |
| `packing_lists/` | Directory for saved draft lists |
| `app.py` | Add `render_packing()` page |

---

## Future: Buffet Templates (36 templates)

For Phase 2+, the buffet Excel contains:
- Breakfast: Buffet Breakfast, Pancake Station, Omelette Station, Eggs Benedict
- Day service: Morning Tea, Lunch, Afternoon Tea (and combos)
- Dinner: Buffet Dinner, BBQ Buffet
- Stations: Bao, Pasta, Taco, Hot Food, Cheese, Smoker, Carving, Paella, Poke, Platter
- Specialty: Gaming Seafood Buffet, Canape, Dessert, Dietary
- Beverage: Smoothie Station, Juice Buffet, T&C Station, Coffee Cart
- Large events: Level 7 Cocktail (250/500/1000 pax variants)

These are more complex with variable item lists per station type. Will tackle after plated is proven.

---

## Implementation Plan

### Step 1: Data Model & Item Database
Create `recon/packing.py` with:
- Item definitions (name, category, formula)
- Template definitions (which items each template includes)
- PackingList model for saving drafts

### Step 2: Build Plated Item Database
Extract from Excel:
- All unique items across 8 plated templates
- Quantity formulas for each
- Default notes (e.g., "Book folded")
- Conditional rules (e.g., dessert spoon only if main/dessert)

### Step 3: Streamlit UI
Add "Packing Lists" page with:
- Event configuration form
- Template selector with visual preview
- Editable item table
- Export button

### Step 4: Excel Export
Generate Excel file matching current format:
- Same layout as existing templates
- PACKED (Y/N) column for manual checking
- NOTES column preserved
- Print-friendly formatting

---

## Ready to Start?

Once confirmed, I'll begin with Step 1: creating the data model and extracting items from the plated Excel into a structured JSON format.
