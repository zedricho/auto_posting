# Parser Testing Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated Parser Testing page with match traces and feedback collection for iteratively refining the EO parser.

**Architecture:** Extend the parser to return match metadata alongside parsed values. Add a new Streamlit page accessible via sidebar that displays detailed extraction info and collects text feedback. Accumulate feedback in session state and export as JSON.

**Tech Stack:** Streamlit, pdfplumber, Pydantic dataclasses, pytest

---

## Task 1: Add MatchTrace Dataclass

**Files:**
- Modify: `recon/models.py`
- Test: `tests/test_parser_traces.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_parser_traces.py`:

```python
"""Tests for parser match trace functionality."""

import pytest
from recon.models import MatchTrace


def test_match_trace_creation():
    """MatchTrace dataclass can be instantiated with required fields."""
    trace = MatchTrace(
        pattern_name="per_person",
        matched_text="1174 Pax @ $105.00",
        extracted={"pax": 1174, "price": 105.0},
        calculation="1174 × $105.00",
        value=123270.0,
    )
    assert trace.pattern_name == "per_person"
    assert trace.matched_text == "1174 Pax @ $105.00"
    assert trace.extracted == {"pax": 1174, "price": 105.0}
    assert trace.calculation == "1174 × $105.00"
    assert trace.value == 123270.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser_traces.py::test_match_trace_creation -v`
Expected: FAIL with "cannot import name 'MatchTrace'"

- [ ] **Step 3: Write minimal implementation**

Add to `recon/models.py` after the imports:

```python
from dataclasses import dataclass
from typing import Any


@dataclass
class MatchTrace:
    """Metadata about how a line was parsed."""
    pattern_name: str          # "per_person", "per_unit", "flat", "hourly", "consumption", "guest_expense"
    matched_text: str          # The raw regex match
    extracted: dict[str, Any]  # {"pax": 1174, "price": 105.0}
    calculation: str           # "1174 × $105.00"
    value: float               # Computed value
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser_traces.py::test_match_trace_creation -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recon/models.py tests/test_parser_traces.py
git commit -m "feat: add MatchTrace dataclass for parser debugging"
```

---

## Task 2: Modify parse_line to Return Traces

**Files:**
- Modify: `recon/parser.py`
- Test: `tests/test_parser_traces.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parser_traces.py`:

```python
from recon.parser import parse_line_with_trace


def test_parse_line_per_person_returns_trace():
    """Per-person pattern returns correct trace metadata."""
    result = parse_line_with_trace("1174 Pax @ $105.00")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "per_person"
    assert "1174 Pax @ $105.00" in trace.matched_text
    assert trace.extracted["pax"] == 1174
    assert trace.extracted["price"] == 105.0
    assert trace.calculation == "1174 × $105.00"
    assert trace.value == 123270.0


def test_parse_line_hourly_returns_trace():
    """Hourly pattern returns correct trace metadata."""
    result = parse_line_with_trace("8 Guards from 11:00 - 16:30 @ $71 Per Hour")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "hourly"
    assert trace.extracted["guards"] == 8
    assert trace.extracted["hours"] == 5.5
    assert trace.extracted["rate"] == 71.0
    assert trace.calculation == "8 × 5.5 × $71.00"
    assert trace.value == 3124.0


def test_parse_line_flat_returns_trace():
    """Flat pattern returns correct trace metadata."""
    result = parse_line_with_trace("Venue Hire @ $5000.00 For This Event")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "flat"
    assert trace.extracted["price"] == 5000.0
    assert trace.calculation == "$5,000.00 flat"
    assert trace.value == 5000.0


def test_parse_line_consumption_returns_trace():
    """Consumption pattern returns correct trace metadata."""
    result = parse_line_with_trace("House Wine on consumption")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "consumption"
    assert trace.calculation == "Manual entry required"
    assert trace.value == 0.0


def test_parse_line_guest_expense_returns_trace():
    """Guest expense pattern returns correct trace metadata."""
    result = parse_line_with_trace("Bar Tab at guest expense")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "guest_expense"
    assert trace.calculation == "Manual entry required"
    assert trace.value == 0.0


def test_parse_line_no_match_returns_none():
    """Lines with no pattern match return None."""
    result = parse_line_with_trace("Some random text without pricing")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser_traces.py -v -k "trace"`
Expected: FAIL with "cannot import name 'parse_line_with_trace'"

- [ ] **Step 3: Write minimal implementation**

Add to `recon/parser.py` after the imports:

```python
from recon.models import MatchTrace
```

Add new function after `parse_line()`:

```python
def parse_line_with_trace(line: str) -> tuple[ParsedLine, MatchTrace] | None:
    """
    Parse a single line and return both ParsedLine and MatchTrace.

    Returns tuple of (ParsedLine, MatchTrace) if matched, None otherwise.
    """
    line_lower = line.lower()

    # Check for consumption (no price, needs manual entry)
    if "on consumption" in line_lower:
        desc = re.sub(r"\s*on consumption\s*", "", line, flags=re.IGNORECASE).strip()
        parsed = ParsedLine(
            description=desc,
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="consumption",
            matched_text=line.strip(),
            extracted={},
            calculation="Manual entry required",
            value=0.0,
        )
        return (parsed, trace)

    # Check for guest expense / cash (no price, needs manual entry)
    if "at guest expense" in line_lower:
        desc = re.sub(r"\s*at guest expense\s*", "", line, flags=re.IGNORECASE).strip()
        parsed = ParsedLine(
            description=desc,
            basis="guest_expense",
            value=0.0,
            money_type="cash",
            posts_to="delphi_only",
            needs_manual_value=True,
        )
        trace = MatchTrace(
            pattern_name="guest_expense",
            matched_text=line.strip(),
            extracted={},
            calculation="Manual entry required",
            value=0.0,
        )
        return (parsed, trace)

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
        value = round(guards * hours * rate, 2)
        parsed = ParsedLine(
            description=line.strip(),
            basis="hourly",
            guards=guards,
            hours=hours,
            unit_price=rate,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="hourly",
            matched_text=security_match.group(0),
            extracted={"guards": guards, "hours": hours, "rate": rate},
            calculation=f"{guards} × {hours} × ${rate:,.2f}",
            value=value,
        )
        return (parsed, trace)

    # Per person pattern: N Pax @ $X (Per Person)
    pax_match = re.search(
        r"(\d+)\s*Pax\s*@\s*\$?([\d,]+\.?\d*)",
        line,
        re.IGNORECASE,
    )
    if pax_match:
        pax = int(pax_match.group(1))
        price = _parse_price(pax_match.group(2))
        value = round(pax * price, 2)
        parsed = ParsedLine(
            description=line.strip(),
            basis="per_person",
            pax=pax,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="per_person",
            matched_text=pax_match.group(0),
            extracted={"pax": pax, "price": price},
            calculation=f"{pax} × ${price:,.2f}",
            value=value,
        )
        return (parsed, trace)

    # Flat "For This Event" pattern: @ $X For This Event
    flat_event_match = re.search(
        r"@\s*\$?([\d,]+\.?\d*)\s*For This Event",
        line,
        re.IGNORECASE,
    )
    if flat_event_match:
        price = _parse_price(flat_event_match.group(1))
        parsed = ParsedLine(
            description=line.strip(),
            basis="flat",
            value=price,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="flat",
            matched_text=flat_event_match.group(0),
            extracted={"price": price},
            calculation=f"${price:,.2f} flat",
            value=price,
        )
        return (parsed, trace)

    # Per unit pattern: N @ $X Per [unit]
    per_unit_match = re.search(
        r"(\d+)\s*@\s*\$?([\d,]+\.?\d*)\s*Per\s+\w+",
        line,
        re.IGNORECASE,
    )
    if per_unit_match:
        qty = int(per_unit_match.group(1))
        price = _parse_price(per_unit_match.group(2))
        value = round(qty * price, 2)
        parsed = ParsedLine(
            description=line.strip(),
            basis="per_unit",
            qty=qty,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="per_unit",
            matched_text=per_unit_match.group(0),
            extracted={"qty": qty, "price": price},
            calculation=f"{qty} × ${price:,.2f}",
            value=value,
        )
        return (parsed, trace)

    # Flat single item pattern: 1 @ $X (no "Per" or "For This Event")
    flat_single_match = re.search(
        r"(\d+)\s*@\s*\$?([\d,]+\.?\d*)(?:\s|$)",
        line,
    )
    if flat_single_match:
        qty = int(flat_single_match.group(1))
        price = _parse_price(flat_single_match.group(2))
        value = round(qty * price, 2)
        parsed = ParsedLine(
            description=line.strip(),
            basis="flat",
            qty=qty,
            unit_price=price,
            value=value,
            money_type="contracted",
            posts_to="both",
        )
        trace = MatchTrace(
            pattern_name="flat_single",
            matched_text=flat_single_match.group(0),
            extracted={"qty": qty, "price": price},
            calculation=f"{qty} × ${price:,.2f}",
            value=value,
        )
        return (parsed, trace)

    # No pattern matched
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser_traces.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recon/parser.py tests/test_parser_traces.py
git commit -m "feat: add parse_line_with_trace for debugging visibility"
```

---

## Task 3: Add parse_pdf_with_traces Function

**Files:**
- Modify: `recon/parser.py`
- Test: `tests/test_parser_traces.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_parser_traces.py`:

```python
from recon.parser import ParseResult


def test_parse_result_dataclass():
    """ParseResult dataclass can be instantiated."""
    from recon.models import EventOrder, MatchTrace
    from recon.parser import ParsedLine

    event = EventOrder(
        pm_number="9353",
        beo_number="2895",
        event_name="Test Event",
        event_date=None,
        line_items=[],
    )

    result = ParseResult(
        event_order=event,
        matched_lines=[],
        unmatched_lines=[],
    )

    assert result.event_order.beo_number == "2895"
    assert result.matched_lines == []
    assert result.unmatched_lines == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_parser_traces.py::test_parse_result_dataclass -v`
Expected: FAIL with "cannot import name 'ParseResult'"

- [ ] **Step 3: Write minimal implementation**

Add to `recon/parser.py` after the `ParsedLine` dataclass:

```python
@dataclass
class ParseResult:
    """Full parse result with traces for debugging."""
    event_order: EventOrder
    matched_lines: list[tuple[str, ParsedLine, MatchTrace]]  # (raw_text, parsed, trace)
    unmatched_lines: list[str]  # Lines that looked like pricing but didn't match
```

Add new function after `parse_pdf()`:

```python
# Keywords that suggest a line might be pricing-related
PRICING_KEYWORDS = ["$", "@", "pax", "per ", "consumption", "expense", "hire", "fee"]


def _looks_like_pricing(line: str) -> bool:
    """Check if a line looks like it might contain pricing info."""
    line_lower = line.lower()
    return any(kw in line_lower for kw in PRICING_KEYWORDS)


def parse_pdf_with_traces(pdf_path: str | Path) -> ParseResult:
    """
    Parse an EO PDF and return detailed trace information.

    Returns ParseResult with:
    - event_order: The parsed EventOrder
    - matched_lines: List of (raw_text, ParsedLine, MatchTrace) tuples
    - unmatched_lines: Lines that look like pricing but didn't match any pattern
    """
    pdf_path = Path(pdf_path)

    with pdfplumber.open(pdf_path) as pdf:
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    # Extract headers
    headers = extract_headers(full_text)

    # Parse event date if present
    event_date = None
    if headers["event_date"]:
        try:
            event_date = datetime.strptime(
                headers["event_date"], "%a %d %b %Y"
            ).date()
        except ValueError:
            pass

    # Parse line items with traces
    line_items: list[LineItem] = []
    matched_lines: list[tuple[str, ParsedLine, MatchTrace]] = []
    unmatched_lines: list[str] = []
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

        # Try to parse the line with trace
        result = parse_line_with_trace(line)
        if result is not None:
            parsed, trace = result
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
            matched_lines.append((line, parsed, trace))
        elif _looks_like_pricing(line):
            # Line looks like it might be pricing but didn't match
            unmatched_lines.append(line)

    event_order = EventOrder(
        pm_number=headers["pm_number"] or "",
        beo_number=headers["beo_number"] or "",
        event_name=headers["event_name"] or "",
        event_date=event_date,
        line_items=line_items,
    )

    return ParseResult(
        event_order=event_order,
        matched_lines=matched_lines,
        unmatched_lines=unmatched_lines,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_parser_traces.py::test_parse_result_dataclass -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recon/parser.py tests/test_parser_traces.py
git commit -m "feat: add parse_pdf_with_traces for detailed extraction info"
```

---

## Task 4: Create Feedback Module

**Files:**
- Create: `recon/feedback.py`
- Create: `tests/test_feedback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_feedback.py`:

```python
"""Tests for feedback module."""

import json
import pytest
from datetime import datetime

from recon.feedback import FeedbackEntry, FeedbackLog, export_feedback_json
from recon.models import MatchTrace


def test_feedback_entry_creation():
    """FeedbackEntry can be instantiated."""
    trace = MatchTrace(
        pattern_name="per_person",
        matched_text="100 Pax @ $50",
        extracted={"pax": 100, "price": 50.0},
        calculation="100 × $50.00",
        value=5000.0,
    )
    entry = FeedbackEntry(
        pdf_name="test.pdf",
        line_text="100 Pax @ $50",
        match_trace=trace,
        category="food",
        note="Looks correct",
        timestamp="2026-06-09T14:30:00",
    )
    assert entry.pdf_name == "test.pdf"
    assert entry.note == "Looks correct"


def test_feedback_entry_unmatched():
    """FeedbackEntry can have None match_trace for unmatched lines."""
    entry = FeedbackEntry(
        pdf_name="test.pdf",
        line_text="Some unmatched line",
        match_trace=None,
        category="beverage",
        note="Should match consumption pattern",
        timestamp="2026-06-09T14:30:00",
    )
    assert entry.match_trace is None
    assert entry.note == "Should match consumption pattern"


def test_feedback_log_add_entry():
    """FeedbackLog can accumulate entries."""
    log = FeedbackLog()
    entry = FeedbackEntry(
        pdf_name="test.pdf",
        line_text="100 Pax @ $50",
        match_trace=None,
        category="food",
        note="Test",
        timestamp="2026-06-09T14:30:00",
    )
    log.add(entry)
    assert len(log.entries) == 1


def test_feedback_log_clear():
    """FeedbackLog can be cleared."""
    log = FeedbackLog()
    log.add(FeedbackEntry(
        pdf_name="test.pdf",
        line_text="100 Pax @ $50",
        match_trace=None,
        category="food",
        note="Test",
        timestamp="2026-06-09T14:30:00",
    ))
    log.clear()
    assert len(log.entries) == 0


def test_export_feedback_json():
    """export_feedback_json produces valid JSON structure."""
    log = FeedbackLog()
    trace = MatchTrace(
        pattern_name="per_person",
        matched_text="100 Pax @ $50",
        extracted={"pax": 100, "price": 50.0},
        calculation="100 × $50.00",
        value=5000.0,
    )
    log.add(FeedbackEntry(
        pdf_name="test.pdf",
        line_text="100 Pax @ $50",
        match_trace=trace,
        category="food",
        note="Correct",
        timestamp="2026-06-09T14:30:00",
    ))
    log.add(FeedbackEntry(
        pdf_name="test.pdf",
        line_text="Unmatched line",
        match_trace=None,
        category="beverage",
        note="Missing pattern",
        timestamp="2026-06-09T14:31:00",
    ))

    result = export_feedback_json(log)
    data = json.loads(result)

    assert "exported_at" in data
    assert data["session_summary"]["total_entries"] == 2
    assert data["session_summary"]["matched_with_notes"] == 1
    assert data["session_summary"]["unmatched_with_notes"] == 1
    assert len(data["entries"]) == 2

    # Check matched entry
    matched = data["entries"][0]
    assert matched["matched"] is True
    assert matched["pattern"] == "per_person"
    assert matched["extracted"] == {"pax": 100, "price": 50.0}

    # Check unmatched entry
    unmatched = data["entries"][1]
    assert unmatched["matched"] is False
    assert unmatched["pattern"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_feedback.py -v`
Expected: FAIL with "No module named 'recon.feedback'"

- [ ] **Step 3: Write minimal implementation**

Create `recon/feedback.py`:

```python
"""Feedback collection for parser refinement."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from recon.models import MatchTrace


@dataclass
class FeedbackEntry:
    """User feedback on a parsed line."""
    pdf_name: str
    line_text: str
    match_trace: MatchTrace | None  # None if line was unmatched
    category: str | None
    note: str
    timestamp: str


@dataclass
class FeedbackLog:
    """Accumulated feedback across PDFs."""
    entries: list[FeedbackEntry] = field(default_factory=list)

    def add(self, entry: FeedbackEntry) -> None:
        """Add an entry to the log."""
        self.entries.append(entry)

    def clear(self) -> None:
        """Clear all entries."""
        self.entries.clear()

    def get_pdf_names(self) -> set[str]:
        """Get unique PDF names in the log."""
        return {e.pdf_name for e in self.entries}


def export_feedback_json(log: FeedbackLog) -> str:
    """Export feedback log as JSON string."""
    matched_count = sum(1 for e in log.entries if e.match_trace is not None)
    unmatched_count = len(log.entries) - matched_count

    entries_data = []
    for entry in log.entries:
        entry_dict: dict[str, Any] = {
            "pdf_name": entry.pdf_name,
            "line_text": entry.line_text,
            "matched": entry.match_trace is not None,
            "category": entry.category,
            "note": entry.note,
            "timestamp": entry.timestamp,
        }

        if entry.match_trace:
            entry_dict["pattern"] = entry.match_trace.pattern_name
            entry_dict["extracted"] = entry.match_trace.extracted
            entry_dict["calculation"] = entry.match_trace.calculation
            entry_dict["value"] = entry.match_trace.value
        else:
            entry_dict["pattern"] = None
            entry_dict["extracted"] = None
            entry_dict["calculation"] = None
            entry_dict["value"] = None

        entries_data.append(entry_dict)

    output = {
        "exported_at": datetime.now().isoformat(),
        "session_summary": {
            "pdfs_processed": len(log.get_pdf_names()),
            "total_entries": len(log.entries),
            "matched_with_notes": matched_count,
            "unmatched_with_notes": unmatched_count,
        },
        "entries": entries_data,
    }

    return json.dumps(output, indent=2)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_feedback.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add recon/feedback.py tests/test_feedback.py
git commit -m "feat: add feedback module for parser refinement"
```

---

## Task 5: Add Sidebar Navigation to App

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Refactor main() to support pages**

Modify `app.py` — replace the `main()` function and add page routing:

```python
def main():
    st.set_page_config(
        page_title="EO Reconciliation Tool",
        page_icon="📊",
        layout="wide",
    )

    # Authentication
    if not check_password():
        st.stop()

    # Sidebar navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Reconciliation", "Parser Testing"],
        label_visibility="collapsed",
    )

    if page == "Reconciliation":
        render_reconciliation()
    else:
        render_parser_testing()


def render_reconciliation():
    """Main reconciliation wizard (4-step flow)."""
    st.title("📊 Event Order Reconciliation Tool")

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


def render_parser_testing():
    """Parser testing page — placeholder for now."""
    st.title("🔬 Parser Testing")
    st.info("Parser testing mode coming soon...")
```

Also move `st.set_page_config()` from top of file into `main()` (it must be the first Streamlit command).

- [ ] **Step 2: Run app locally to verify navigation works**

Run: `streamlit run app.py`
Expected: Sidebar with "Reconciliation" and "Parser Testing" options. Switching between them works.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: add sidebar navigation with parser testing placeholder"
```

---

## Task 6: Implement Parser Testing Page

**Files:**
- Modify: `app.py`

- [ ] **Step 1: Add imports for parser testing**

Add to imports at top of `app.py`:

```python
from datetime import datetime
from recon.parser import parse_pdf_with_traces, ParseResult
from recon.feedback import FeedbackEntry, FeedbackLog, export_feedback_json
from recon.models import MatchTrace
```

- [ ] **Step 2: Implement render_parser_testing()**

Replace the placeholder `render_parser_testing()` with:

```python
def render_parser_testing():
    """Parser testing page for refining extraction patterns."""
    st.title("🔬 Parser Testing")
    st.write("Upload EO PDFs to see detailed extraction traces and provide feedback.")

    # Initialize parser testing session state
    if "pt_result" not in st.session_state:
        st.session_state.pt_result = None
    if "pt_pdf_name" not in st.session_state:
        st.session_state.pt_pdf_name = None
    if "pt_feedback_log" not in st.session_state:
        st.session_state.pt_feedback_log = FeedbackLog()
    if "pt_notes" not in st.session_state:
        st.session_state.pt_notes = {}

    # Show feedback log status
    log = st.session_state.pt_feedback_log
    if log.entries:
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**Feedback Log:** {len(log.entries)} entries")
        st.sidebar.markdown(f"PDFs: {', '.join(log.get_pdf_names())}")

    # Upload section
    st.subheader("1. Upload PDF")
    uploaded_file = st.file_uploader("Choose an EO PDF", type=["pdf"], key="pt_uploader")

    if uploaded_file is not None:
        if st.button("Extract with Traces"):
            with st.spinner("Extracting..."):
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name

                try:
                    result = parse_pdf_with_traces(tmp_path)
                    st.session_state.pt_result = result
                    st.session_state.pt_pdf_name = uploaded_file.name
                    st.session_state.pt_notes = {}  # Reset notes for new PDF
                    st.success(f"Extracted {len(result.matched_lines)} matched lines, {len(result.unmatched_lines)} unmatched")
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    os.unlink(tmp_path)

    # Show results if available
    if st.session_state.pt_result is not None:
        result = st.session_state.pt_result
        pdf_name = st.session_state.pt_pdf_name

        # Event info
        st.divider()
        event = result.event_order
        st.subheader("Event Details")
        cols = st.columns(3)
        cols[0].metric("PM#", event.pm_number or "—")
        cols[1].metric("BEO#", event.beo_number or "—")
        cols[2].metric("Event", event.event_name or "—")

        # Matched lines table
        st.divider()
        st.subheader(f"2. Matched Lines ({len(result.matched_lines)})")

        for i, (raw_text, parsed, trace) in enumerate(result.matched_lines):
            with st.expander(f"**{parsed.description[:60]}...**" if len(parsed.description) > 60 else f"**{parsed.description}**"):
                col1, col2 = st.columns([2, 1])
                with col1:
                    st.markdown(f"**Pattern:** `{trace.pattern_name}`")
                    st.markdown(f"**Matched:** `{trace.matched_text}`")
                    st.markdown(f"**Extracted:** `{trace.extracted}`")
                    st.markdown(f"**Calculation:** {trace.calculation}")
                    st.markdown(f"**Value:** ${trace.value:,.2f}")
                    st.markdown(f"**Category:** {parsed.description}")
                with col2:
                    note_key = f"matched_{i}"
                    note = st.text_area(
                        "Feedback note",
                        value=st.session_state.pt_notes.get(note_key, ""),
                        key=f"note_{note_key}",
                        height=100,
                    )
                    st.session_state.pt_notes[note_key] = note

        # Unmatched lines
        if result.unmatched_lines:
            st.divider()
            st.subheader(f"3. Unmatched Lines ({len(result.unmatched_lines)})")
            st.warning("These lines look like they might contain pricing but didn't match any pattern.")

            for i, line in enumerate(result.unmatched_lines):
                with st.expander(f"**{line[:60]}...**" if len(line) > 60 else f"**{line}**"):
                    st.code(line)
                    note_key = f"unmatched_{i}"
                    note = st.text_area(
                        "What should this be?",
                        value=st.session_state.pt_notes.get(note_key, ""),
                        key=f"note_{note_key}",
                        height=100,
                    )
                    st.session_state.pt_notes[note_key] = note

        # Actions
        st.divider()
        st.subheader("4. Actions")

        col1, col2, col3 = st.columns(3)

        with col1:
            if st.button("Add to Feedback Log"):
                # Add matched lines with notes
                for i, (raw_text, parsed, trace) in enumerate(result.matched_lines):
                    note = st.session_state.pt_notes.get(f"matched_{i}", "")
                    if note:  # Only add if there's a note
                        entry = FeedbackEntry(
                            pdf_name=pdf_name,
                            line_text=raw_text,
                            match_trace=trace,
                            category=parsed.basis,
                            note=note,
                            timestamp=datetime.now().isoformat(),
                        )
                        log.add(entry)

                # Add unmatched lines with notes
                for i, line in enumerate(result.unmatched_lines):
                    note = st.session_state.pt_notes.get(f"unmatched_{i}", "")
                    if note:  # Only add if there's a note
                        entry = FeedbackEntry(
                            pdf_name=pdf_name,
                            line_text=line,
                            match_trace=None,
                            category=None,
                            note=note,
                            timestamp=datetime.now().isoformat(),
                        )
                        log.add(entry)

                st.success(f"Added to log. Total entries: {len(log.entries)}")
                st.rerun()

        with col2:
            if log.entries:
                json_data = export_feedback_json(log)
                st.download_button(
                    f"Download Feedback ({len(log.entries)} entries)",
                    data=json_data,
                    file_name=f"parser_feedback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                    mime="application/json",
                )

        with col3:
            if log.entries:
                if st.button("Clear Log"):
                    log.clear()
                    st.success("Log cleared")
                    st.rerun()
```

- [ ] **Step 3: Run app and test parser testing page**

Run: `streamlit run app.py`
Expected:
- Parser Testing page shows upload UI
- Uploading a PDF shows matched lines with traces
- Each line has expandable details with pattern, extracted values, calculation
- Notes can be entered per line
- "Add to Feedback Log" saves entries with notes
- "Download Feedback" exports JSON
- "Clear Log" clears accumulated feedback

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: implement parser testing page with match traces and feedback"
```

---

## Task 7: Update Package Exports

**Files:**
- Modify: `recon/__init__.py`

- [ ] **Step 1: Add new exports**

Update `recon/__init__.py` to include new classes:

```python
"""Event Order Reconciliation package."""

from recon.models import (
    LineItem,
    EventOrder,
    CategoryTotals,
    WorksheetOutput,
    MatchTrace,
)
from recon.parser import (
    parse_pdf,
    parse_pdf_with_traces,
    parse_line,
    parse_line_with_trace,
    extract_headers,
    ParseResult,
)
from recon.builder import compute_totals, generate_excel
from recon.reconciler import reconcile, Discrepancy
from recon.delphi_adapter import parse_delphi_report
from recon.feedback import FeedbackEntry, FeedbackLog, export_feedback_json

__all__ = [
    # Models
    "LineItem",
    "EventOrder",
    "CategoryTotals",
    "WorksheetOutput",
    "MatchTrace",
    # Parser
    "parse_pdf",
    "parse_pdf_with_traces",
    "parse_line",
    "parse_line_with_trace",
    "extract_headers",
    "ParseResult",
    # Builder
    "compute_totals",
    "generate_excel",
    # Reconciler
    "reconcile",
    "Discrepancy",
    # Delphi
    "parse_delphi_report",
    # Feedback
    "FeedbackEntry",
    "FeedbackLog",
    "export_feedback_json",
]
```

- [ ] **Step 2: Run all tests to verify nothing broke**

Run: `pytest -v`
Expected: All tests pass

- [ ] **Step 3: Commit**

```bash
git add recon/__init__.py
git commit -m "feat: export new parser testing classes from package"
```

---

## Task 8: Push to GitHub

**Files:** None (git operation)

- [ ] **Step 1: Push all commits**

```bash
git push origin main
```

- [ ] **Step 2: Verify on GitHub**

Check that all new commits appear at https://github.com/zedricho/auto_posting

---

## Summary

| Task | Description |
|------|-------------|
| 1 | Add MatchTrace dataclass to models |
| 2 | Add parse_line_with_trace() function |
| 3 | Add parse_pdf_with_traces() and ParseResult |
| 4 | Create feedback module with export |
| 5 | Add sidebar navigation to app |
| 6 | Implement parser testing page UI |
| 7 | Update package exports |
| 8 | Push to GitHub |
