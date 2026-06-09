# Event Order Reading Library

**Purpose:** This is the single source of truth for how an Event Order (EO) from The Star Brisbane is read, how its figures are computed, and how they map into Delphi revenue columns and the Opera posting. It is used two ways:

1. As **context for the Reader** (the extraction step) — fed alongside each EO so the model knows the rules and category mappings.
2. As the **spec** the worksheet Builder and Reconciler are built against.

When in doubt, this document wins over intuition. Update it whenever a new nuance appears; the worked example in §14 is the canonical target output.

---

## 1. The two systems and why they differ

- **Delphi** records *all* revenue, **including cash/guest-expense sales**.
- **Opera** records only what the client is **posted/billed** — it **excludes cash sales** (the guest already paid at point of sale).

Every figure in the worksheet exists to support that split. Get the money-type of each line right (§7) and the rest follows.

---

## 2. Document anatomy

- An EO PDF may contain **one or several BEOs** (bookings), e.g. a low-risk bump-in day plus the main event day.
- Each BEO starts a fresh sequence with its own header showing the **event name**, **event date**, and **BEO#**.
- Delphi posts **per day / per BEO**. The tool therefore works on **one BEO at a time** — the operator selects the relevant BEO from the PDF, and **exactly one worksheet is generated per run**.
- A single EO is structured top-to-bottom as: header block → function/time grid → Synopsis → Menu Content → Dietary → Beverage Selection → Set Up → Signage → Contractors → WHS → Audio Visual → Security → Billing Instruction.

---

## 3. Identifiers

| Field | Where it appears | Behaviour |
|---|---|---|
| **PM# (Posting Master)** | Top-right header, every page (`Posting Master #: 9353`) | **Constant for the whole event** — all BEOs of one event share it. |
| **BEO#** | Top-right header (`BEO#: 2895`) | **Varies per booking.** This is the key the reconciliation matches on. |
| **Event name** | Header `Post As:` line | Constant per event. |
| **Event date** | Header `Event Date:` | Per BEO (different days have different BEOs). |

The reader must always capture PM# and BEO# — PM# groups, BEO# identifies.

---

## 4. Delphi revenue columns

Delphi exposes these revenue columns (plus a Total): **Food, Beverage, Resource, Other, AV, Venue Hire, On Charge**.

In practice only five are used: **Food, Beverage, Resource, Other, Venue Hire.**

- **AV** — almost always external ("AVP to bill direct") and posts **$0**. GST is the only place AV ever needs special handling (see §8).
- **On Charge** — **not used** unless explicitly instructed otherwise. Default it to $0.

---

## 5. Section → column mapping

| EO section / line type | Delphi column |
|---|---|
| Menu Content (plated meals, crew meals) | **Food** |
| Beverage Selection (packages, cartons, consumption, guest-expense spirits) | **Beverage** |
| Security | **Other** |
| Additional resources — FOH bar hire, coffee cart hire, labour surcharge, red carpet | **Resource** |
| Venue Hire / Minimum spend | **Venue Hire** |
| Audio Visual | **AV** (usually $0, bill direct) |

Exceptions are flagged inline in the EO; if a line doesn't obviously fit, route it to review rather than guessing.

---

## 6. Computing line values

Contracted lines always state a price using an `@` pattern. Compute the value from the pattern:

| Pattern in EO | Example | Value |
|---|---|---|
| `N Pax @ $X Per Person` | `1174 Pax @ $105.00` | pax × price = 123,270.00 |
| `N @ $X Per Bar` / `Per 8m piece` / per unit | `2 Red carpet @ $150.00 Per 8m piece` | qty × price = 300.00 |
| `@ $X For This Event` (flat) | Labour surcharge `@ $320.00 For This Event` | 320.00 |
| `1 @ $X` (flat one-off) | `XXXX Cartons 1 @ $2,702.63` | 2,702.63 |
| Security `N Guards from HH:MM - HH:MM @ $X Per Hour` | `8 Guards 11:00–16:30 @ $71.00` | guards × hours × rate = 8 × 5.5 × 71 = 3,124.00 |

Lines with **no price stated** are not contracted — they are consumption or cash (see §7) and their value comes from outside the EO.

---

## 7. The three money types  ⟵ core logic

This is the distinction the whole tool turns on. The EO is written **before** the event, so consumption and cash have **no dollar figure in it** — they look similar on the page but behave oppositely once actuals land.

| Type | Trigger phrase in EO | Has EO $ value? | Source of figure | Posts to Delphi | Posts to Opera | Counts toward min spend? |
|---|---|---|---|---|---|---|
| **Contracted** | priced `@` line | Yes | EO computation (§6) | ✅ | ✅ | ✅ |
| **Consumption** | **"on consumption"** | No | **Keyed manually post-event** (actual stock consumed; billed to client) | ✅ | ✅ (posts as **beverage**) | ✅ |
| **Cash / guest expense** | **"at guest expense"** | No | **POS / day sales** | ✅ | ❌ **never** | ❌ (guest paid, not client) |

Notes:
- The trigger phrases are **reliable**: it will always be exactly *"on consumption"* or *"at guest expense"*. Anything else is contracted.
- **Consumption and cash are EO twins, Opera opposites:** both blank in the EO and both need an external figure, but consumption goes **into** Opera while cash stays **out**.
- A consumption line marked **complimentary** (e.g. "Secretariat included complimentary") posts **$0**.
- Misreading a cash line as consumption wrongly inflates Opera and the client's min-spend position — this is the highest-cost extraction error, so low-confidence cases route to review.

---

## 8. GST

- Reconciliation runs **GST-inclusive end to end**. All figures above are inc-GST.
- The **only** place GST needs special handling is **AV/AVP** (Disc inc GST / Owing inc GST), and AV is usually external anyway.

---

## 9. Venue hire & the minimum-spend waterfall

Venue hire is a **decision with a default**, not a fixed formula. The operator confirms it; the tool computes and surfaces the inputs.

**Default rule:**
- **F&B min spend met → venue hire = flat fee** (the room's stated hire; rooms in the function/time grid top section are typically flat). Ultimate Origin: min met, so venue hire is simply the **$500** green-room fee.
- **F&B min spend NOT met → venue hire = the shortfall figure** (the top-up needed to reach the floor). Case-by-case beyond that.

**The waterfall (worked with a $100k floor, $90k F&B):**
1. F&B actual = food + beverage contracted **+ consumption keyed post-event**. (Cash sales do **not** count.)
2. Shortfall = floor − F&B actual = 100k − 90k = **10k**.
3. Shortfall is booked as venue hire to reach the floor.
4. Consumption then lands — say $4k drunk on the night. It posts as **beverage**, lifting F&B to 94k, so shortfall drops to **6k** and the venue-hire top-up falls with it.

The structure is self-balancing: F&B + shortfall-venue-hire = the floor, until F&B alone clears it (shortfall → 0, leaving only flat hire).

**Tool behaviour:** compute F&B actual, the floor, and the shortfall; present them; mark venue hire as **operator-confirmed** rather than auto-posting (case-by-case). Consumption must be keyed **before** venue hire is finalised, since it changes the shortfall.

> The deeper consumption-tab mechanics are to be documented here once explained — placeholder.

---

## 10. Day Delegate Packages (DDP)

Some events use a single per-person package price that splits internally across **food / beverage / resource**.

- Each package is **named**, and each named package has a **fixed dollar split** (per-person dollars that sum to the package price — e.g. a $105 package = $89 food + $6 beverage + $10 resource, *illustrative*).
- The reader identifies a DDP by **matching the package name** against the split table below, then explodes the per-person price into its three category amounts before computing totals.

**DDP split cheat sheet** *(to be supplied — placeholder):*

| Package name | Price pp | Food pp | Beverage pp | Resource pp |
|---|---|---|---|---|
| _TBA_ | | | | |

---

## 11. Multi-BEO documents

- One PDF may hold several BEOs under one PM#.
- The tool processes **one BEO per run**, operator-selected, producing **one worksheet**.
- Reconciliation matches by **BEO#** against the corresponding per-day Delphi posting.
- $0 bump-in days (nothing to post) — *confirm handling: typically skipped; flag if a worksheet is ever needed for them.*

---

## 12. Reconciliation

**Direction of truth:** the worksheet is the *should-be* — EO-contracted figures, plus consumption keyed from the consumption tab, plus cash read from POS. The **Delphi posting report is the as-posted**, checked against it. Consumption and cash enter the worksheet **from the operator's side**, never from the same Delphi report being reconciled (or they'd match trivially).

**Level:** reconcile at **category subtotal per BEO** (Food / Beverage / Resource / Other / Venue Hire) — **not line-by-line**. Delphi groups differently from the EO (e.g. the beverage package and the cash spirits both land inside Delphi's single "Lunch – Plated" row), so line matching would throw false mismatches.

For each category: compute variance vs the posting report, apply a small rounding tolerance, and classify (§13).

---

## 13. Discrepancy diagnostics

Likely causes, in rough order of frequency:

- **Variance ≈ a cash line** → cash sale posted to Opera by mistake (should be Delphi-only), or vice versa.
- **Variance ≈ a consumption line** → consumption not keyed, or keyed to the wrong category (should be beverage).
- **Variance / expected ≈ 1/11 or 0.10** → GST treatment mismatch.
- **Variance = a whole line's value** → that line wasn't posted.
- **Category present one side, absent the other** → missing/extra line.
- **DDP category amounts don't sum to the package price** → split applied wrong.
- **Venue hire ≠ flat fee when min spend met, or ≠ shortfall when not** → min-spend waterfall not applied.
- **Within rounding tolerance** → rounding only, no action.

Core engine is deterministic; an LLM may suggest causes for fuzzy cases but never computes figures.

---

## 14. Gold-standard worked example — BEO 2895

**Ultimate Origin Lunch 2026 · PM 9353 · BEO 2895 · Fri 05 Jun 2026 · Min F&B spend $100,000 (met)**

| EO line | Section → Column | Basis | Value | Money type | Delphi | Opera |
|---|---|---|---|---|---|---|
| Plated Meal – 3 Courses, 1174 @ $105 | Menu → Food | per person | 123,270.00 | contracted | ✅ | ✅ |
| AV Partners Crew Meals, 4 @ $49 | Menu → Food | per person | 196.00 | contracted | ✅ | ✅ |
| XXXX Cartons, 1 @ $2,702.63 | Bev → Beverage | flat | 2,702.63 | contracted | ✅ | ✅ |
| Speaker & VIP Drinks (Green Room) | Bev → Beverage | **on consumption** | 326.00 | consumption | ✅ | ✅ |
| Classic Beverage Package, 1174 @ $63 | Bev → Beverage | per person | 73,962.00 | contracted | ✅ | ✅ |
| Basic Spirits **at guest expense** | Bev → Beverage | POS | 4,848.97 | **cash** | ✅ | ❌ |
| Labour surcharge (cartons) @ $320 | Resource | flat | 320.00 | contracted | ✅ | ✅ |
| Front of House Bar, 1 @ $530 | Resource | per bar | 530.00 | contracted | ✅ | ✅ |
| Red Carpet, 2 @ $150 | Resource | per unit | 300.00 | contracted | ✅ | ✅ |
| Security, 8 guards 11:00–16:30 @ $71/hr | Security → Other | guard-hours × rate (44 × 71) | 3,124.00 | contracted | ✅ | ✅ |
| Green Room Hire | Venue Hire | flat (min met) | 500.00 | contracted | ✅ | ✅ |
| Audio Visual | AV | external | 0.00 | external | — | — |

**Category subtotals**

| Column | Delphi (incl cash) | Opera (excl cash) |
|---|---|---|
| Food | 123,466.00 | 123,466.00 |
| Beverage | 81,839.60 | 76,990.63 |
| Resource | 1,150.00 | 1,150.00 |
| Other | 3,124.00 | 3,124.00 |
| Venue Hire | 500.00 | 500.00 |
| **Total** | **210,079.61** | **205,230.63** |

The 4,848.97 difference between the two totals is exactly the basic-spirits cash sale. Cross-checks: Delphi groups the beverage package + cash spirits into its "Lunch – Plated" row (73,962.00 + 4,848.97 = 78,810.97); the bump-in row carries a 1¢ rounding artefact on the cartons (3,022.64 vs 3,022.63).

**Target extraction (the JSON the Reader should produce):**

```json
{
  "pm_number": "9353",
  "beo_number": "2895",
  "event_name": "Ultimate Origin Lunch 2026",
  "event_date": "2026-06-05",
  "min_fb_spend": 100000.00,
  "min_fb_spend_met": true,
  "line_items": [
    {"category":"food","type":"Plated Meal - 3 Courses","basis":"per_person","pax":1174,"unit_price":105.00,"value":123270.00,"money_type":"contracted","posts_to":"both"},
    {"category":"food","type":"AV Partners Crew Meals","basis":"per_person","pax":4,"unit_price":49.00,"value":196.00,"money_type":"contracted","posts_to":"both"},
    {"category":"beverage","type":"XXXX Cartons","basis":"flat","qty":1,"unit_price":2702.63,"value":2702.63,"money_type":"contracted","posts_to":"both"},
    {"category":"beverage","type":"Speaker & VIP Drinks (Green Room)","basis":"consumption","value":326.00,"money_type":"consumption","posts_to":"both","source":"keyed_post_event"},
    {"category":"beverage","type":"Classic Beverage Package - 4.5 Hours","basis":"per_person","pax":1174,"unit_price":63.00,"value":73962.00,"money_type":"contracted","posts_to":"both"},
    {"category":"beverage","type":"Basic Spirits at Guest Expense","basis":"guest_expense","value":4848.97,"money_type":"cash","posts_to":"delphi_only","source":"pos"},
    {"category":"resource","type":"Labour surcharge - XXXX Cartons","basis":"flat","value":320.00,"money_type":"contracted","posts_to":"both"},
    {"category":"resource","type":"Front of House Bar","basis":"per_unit","qty":1,"unit_price":530.00,"value":530.00,"money_type":"contracted","posts_to":"both"},
    {"category":"resource","type":"Red Carpet","basis":"per_unit","qty":2,"unit_price":150.00,"value":300.00,"money_type":"contracted","posts_to":"both"},
    {"category":"other","type":"Security - 8 guards 11:00-16:30","basis":"hourly","guards":8,"hours":5.5,"rate":71.00,"value":3124.00,"money_type":"contracted","posts_to":"both"},
    {"category":"venue_hire","type":"Green Room Hire","basis":"flat","value":500.00,"money_type":"contracted","posts_to":"both"},
    {"category":"av","type":"Audio Visual","basis":"external","value":0.00,"money_type":"external","posts_to":"none","note":"AVP to bill direct"}
  ]
}
```

> **Golden test:** the Builder fed this JSON must reproduce Delphi 210,079.61 and Opera 205,230.63 exactly, with the category subtotals above. This is the first thing to make pass.

---

## 15. Open items to supply / confirm

- **DDP split cheat sheet** — named packages and their food/bev/resource per-person splits (§10).
- **Consumption-tab mechanics** — the detailed walkthrough to expand §9.
- **$0 bump-in day handling** — confirm whether these are ever reconciled or always skipped (§11).
- **Delphi report format & permissions** — export type (CSV/Excel/API) once access is confirmed, to finalise the ingestion adapter.
