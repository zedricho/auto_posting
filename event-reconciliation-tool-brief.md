# Event Order Reconciliation Tool — Implementation Brief

**For:** Claude Code
**Owner:** Zak
**Goal:** Replace the slow, manual sales-posting process with a tool that reads an event order (EO), rebuilds the reconciliation worksheet automatically, ingests the Delphi posting report, and flags discrepancies with likely causes.

---

## 1. What this tool does (the pipeline)

```
EO PDF ──▶ Reader ──▶ [human review/correct] ──▶ Builder ──▶ worksheet.xlsx
                                                     │
                              Delphi posting report ─┤
                                                     ▼
                                                 Reconciler ──▶ discrepancy report
```

1. **Reader** — extract line items and totals from a text-based EO PDF into a validated, structured object.
2. **Human review** — operator confirms/corrects the extraction before any money is computed. Corrections feed back as new examples.
3. **Builder** — deterministically rebuild the reconciliation worksheet (Delphi totals + Opera totals + GST) and export `.xlsx`.
4. **Reconciler** — diff the computed figures against the Delphi posting report and explain each variance.

---

## 2. Core business logic (this is the spec the math must satisfy)

Reverse-engineered from the existing worksheet. **Confirm each rule with Zak before building.**

- **Delphi totals INCLUDE cash sales. Opera totals EXCLUDE cash sales.**
  Worked example (Beverage): `76,990.63 (Opera, excl cash) + 4,848.97 (cash) = 81,839.60 (Delphi, incl cash)`.
  Food has no cash line, so Delphi and Opera both = `123,466.00`.
- **The OPERA grand total** = Opera Food + Opera Beverage + Resources + Security + Venue Hire (+ AVP if applicable).
  Worked example: `123,466.00 + 76,990.63 + 1,150.00 + 3,124.00 + 500.00 = 205,230.63`.
- **Category sub-totals:**
  - Resources = sum of additional-resource lines (`530 + 300 + 320 = 1,150.00`).
  - Security/Other = `hours × rate` (`44 × 71 = 3,124.00`).
  - Venue Hire = flat amount (`500.00`).
- **Every line item carries an `is_cash_sale` flag** — this single flag drives the Delphi vs Opera split.
- **GST:** Australian GST = 10%. Some columns are marked "inc GST". GST treatment per category is **a spec item to confirm** — do not assume. Many reconciliation breaks are GST-treatment mismatches, so get this exact.
- **Rounding:** to 2 dp. Decide and document **sum-then-round vs round-then-sum** (it affects reconciliation tolerances).

> **Acceptance test #1 (the golden fixture):** Given the existing example EO, the Builder must reproduce every category total and the OPERA total of `205,230.63` exactly. Encode this as a test before building anything else.

---

## 3. Canonical data model

Everything speaks this schema (use **pydantic v2** for validation).

```python
class LineItem(BaseModel):
    category: Literal["food","beverage","additional_resources",
                      "other_security","avp","venue_hire"]
    type: str                 # e.g. "3 Course", "XXXX Cartons", "FOH Bar"
    qty_or_pax: float | None
    unit_cost: float | None
    total: float
    is_cash_sale: bool = False
    gst_treatment: Literal["inc","ex","na"] = "na"
    notes: str | None = None

class EventOrder(BaseModel):
    eo_number: str
    pm_number: str
    event_name: str
    event_date: date | None
    line_items: list[LineItem]

class CategoryTotals(BaseModel):
    category: str
    opera_total: float        # excl cash
    delphi_total: float       # incl cash

class WorksheetTotals(BaseModel):
    by_category: list[CategoryTotals]
    opera_grand_total: float
    delphi_grand_total: float
```

---

## 4. Component specs

### 4.1 Reader (EO extraction)

**Input:** text-based PDF. **Output:** validated `EventOrder`.

Two layers:
- **Deterministic anchors** for the stable bits — `EO:`, `PM:`, event title, the fixed category headers (Food / Beverage / Additional Resources / Other-Security / AVP / Venue Hire). Use `pdfplumber` (good positional/table extraction) or `pymupdf` as fallback.
- **LLM-assisted extraction** (Anthropic SDK) for the nuanced bits: feed the extracted text + the JSON schema + Zak's example/rule library, return JSON, validate against pydantic. If validation fails or confidence is low → route to human review, never silently accept.

**The "training" mechanism (set expectations clearly):** this is *not* fine-tuning. It's a maintained library of:
- a `rules.yaml` (field mappings, category aliases, how to flag cash sales, GST defaults), and
- a `examples/` folder of worked EO→JSON pairs used as few-shot context.

Every operator correction in the review step can be saved as a new example. That is how the Reader "gets trained over time."

### 4.2 Human review step
Show the proposed extraction as an editable table next to the source PDF. Operator confirms/edits, then commits. Required before Builder runs — financial accuracy depends on it.

### 4.3 Builder
Pure, deterministic computation from the validated `EventOrder`:
- per-category Opera (non-cash sum) and Delphi (all sum) totals,
- apply confirmed GST rules,
- apply documented rounding rule,
- export `.xlsx` matching the **current** worksheet layout (openpyxl).

> Note: the existing example layout is outdated. **Task 0 is to lock the current desired layout** (columns, order, formulas, formatting) with Zak before building the exporter.

### 4.4 Delphi posting report ingestion (adapter pattern)
Permissions are TBD, so isolate this behind an interface:

```python
class PostingReportSource(Protocol):
    def load(self) -> PostingReport: ...
```

Implementations, in priority order:
1. `FileImportSource` — CSV/Excel export. **Build this first; it works regardless of permissions.**
2. `ApiSource` — if/when API access is granted.
3. `PasteSource` — manual paste fallback.

All normalise to one `PostingReport` (posted lines: category/account, amount, GST, cash flag if present, EO/PM references).

### 4.5 Reconciler + diagnostics (the high-value part)
Compare computed figures vs the posting report at three levels: **grand total → per category → line level** (match by type/description where possible). For each comparison: variance, tolerance check, and a **plain-language likely cause**.

Core engine is **rule-based and deterministic** (explainable, auditable). Optionally add an LLM "second opinion" for fuzzy cases — but the LLM never computes money, only suggests causes.

Diagnostic heuristics to implement:
- Variance ≈ a cash-sales line → "cash sales likely on the wrong side (Delphi vs Opera)." *(most common given the split)*
- Variance / expected ≈ `1/11` or `0.10` → "GST treatment mismatch."
- Variance equals a specific line total → "line *X* appears not to have been posted."
- Line present in EO but absent in posting (or vice versa) → "missing/extra line."
- `qty` vs `pax` mismatch → "quantity basis mismatch."
- Beverage package vs itemised → "package posted as items (or vice versa)."
- Within rounding tolerance → "rounding only, no action."

---

## 5. Recommended stack

- Python 3.11+
- `pdfplumber` (extraction; `pymupdf` fallback)
- `pydantic` v2 (schema/validation)
- `anthropic` SDK (extraction + optional diagnostics)
- `openpyxl` (worksheet export)
- `pandas` (reconciliation diffing)
- `streamlit` (shared team UI for v1)
- `pytest` (mandatory — financial logic must be tested)
- `ruff` + `black`

**UI choice:** Streamlit for v1 — fast, Python-native, handles upload → review → export, usable by a small team. **Hosting caveat:** casino financial data → deploy internally only (private network / VPN), add simple auth, no public URL. If it later needs to scale or integrate, migrate the core (which is UI-agnostic) behind a FastAPI backend.

---

## 6. Suggested project structure

```
event-recon/
├── app.py                  # Streamlit entry
├── recon/
│   ├── models.py           # pydantic schema
│   ├── reader/
│   │   ├── extract.py      # pdf text + anchors
│   │   ├── llm.py          # LLM extraction
│   │   ├── rules.yaml
│   │   └── examples/
│   ├── builder.py          # totals + xlsx export
│   ├── delphi/
│   │   ├── base.py         # PostingReportSource protocol
│   │   └── file_import.py
│   ├── reconciler.py
│   └── diagnostics.py
├── tests/
│   ├── test_builder_golden.py   # reproduces 205,230.63
│   ├── test_reconciler.py
│   └── fixtures/
└── pyproject.toml
```

---

## 7. Milestones & acceptance criteria

**Phase 0 — Spec lock (no code)**
- Confirm the business rules in §2 with Zak.
- Lock the *current* worksheet layout/columns/GST/rounding rules.
- Collect 3–5 representative sample EO PDFs + the matching correct worksheets.
- *Done when:* rules and target layout are written down and signed off.

**Phase 1 — Schema + Builder + golden test**
- Implement models + Builder.
- *Done when:* the example EO reproduces every category total and `205,230.63` exactly in tests.

**Phase 2 — Reader + review loop**
- PDF extraction + LLM extraction + review UI + example library.
- *Done when:* the sample EOs extract correctly after at most light correction, and corrections persist as examples.

**Phase 3 — Delphi file-import adapter**
- `FileImportSource` → normalised `PostingReport`.
- *Done when:* a sample export loads into the canonical model.

**Phase 4 — Reconciler + diagnostics**
- Three-level diff + heuristic causes.
- *Done when:* known seeded discrepancies (cash-side, GST, missing line) are each correctly identified and explained.

**Phase 5 — UI polish, export, deploy**
- End-to-end flow, downloadable worksheet + reconciliation summary, internal deploy + auth, audit log of extractions/corrections/reconciliations.

---

## 8. Non-negotiable design principles

1. **Money is deterministic.** All totals and reconciliation math are plain Python, unit-tested. LLMs only extract (then validated) and advise on causes — never compute figures.
2. **Human-in-the-loop before posting.** No silent extraction errors reach the worksheet.
3. **The example worksheet is the first test fixture** and the trust gate.
4. **Adapter at the Delphi boundary** so unknown permissions never block progress.
5. **Audit trail.** Log every extraction, correction, and reconciliation for traceability.

---

## 9. Open items to resolve with Zak

- Exact GST treatment per category (inc/ex).
- Rounding convention (sum-then-round vs round-then-sum).
- Final current worksheet layout (the example is outdated).
- Delphi report format once permissions are confirmed.
- How AVP figures behave (Disc/Owing inc GST) — under-specified in the example.
