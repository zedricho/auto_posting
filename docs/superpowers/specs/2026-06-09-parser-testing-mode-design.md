# Parser Testing Mode — Design Spec

**Date:** 2026-06-09
**Owner:** Zak
**Status:** Approved

## Overview

A dedicated "Parser Testing" page in the Streamlit app for iteratively refining the EO parser. Upload PDFs, see detailed match traces showing how each line was parsed, add feedback notes, and export accumulated feedback for pattern improvements.

## Scope

**In scope:**
- Separate page accessible via sidebar navigation
- Match trace display: pattern → matched text → extracted values → calculation
- Text notes field per line item for describing issues
- Unmatched lines section showing missed content
- Feedback accumulation across multiple PDFs in session
- JSON export of feedback log
- Clear log functionality

**Out of scope:**
- Automatic pattern learning
- Persistent storage of feedback (session only)
- Direct pattern editing in UI

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Streamlit App                           │
├─────────────────────────────────────────────────────────────┤
│  Sidebar Navigation                                         │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Reconciliation  │  │ Parser Testing  │                  │
│  └─────────────────┘  └─────────────────┘                  │
├─────────────────────────────────────────────────────────────┤
│  Parser Testing Page                                        │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ 1. Upload PDF                                           ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 2. Matched Lines Table                                  ││
│  │    Pattern | Matched Text | Extracted | Calc | Value    ││
│  │    [Note field per row]                                 ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 3. Unmatched Lines                                      ││
│  │    [Raw text of lines that didn't match any pattern]    ││
│  ├─────────────────────────────────────────────────────────┤│
│  │ 4. Actions                                              ││
│  │    [Add to Log] [Download Feedback] [Clear Log]         ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
```

**Modified modules:**
- `recon/parser.py` — Add `MatchTrace` dataclass, modify `parse_line()` to return trace metadata
- `app.py` — Add sidebar navigation, new `render_parser_testing()` page

**New modules:**
- `recon/feedback.py` — `FeedbackEntry` model and JSON export function

## Data Model

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

@dataclass
class ParsedLineWithTrace:
    """ParsedLine plus match trace for debugging."""
    parsed: ParsedLine
    trace: MatchTrace

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
    entries: list[FeedbackEntry]
```

## Parser Changes

Modify `parse_line()` to return `ParsedLineWithTrace | None` instead of `ParsedLine | None`.

Each pattern match builds a `MatchTrace` with:
- `pattern_name`: Which pattern matched (e.g., "per_person")
- `matched_text`: The substring that matched the regex
- `extracted`: Dictionary of extracted values
- `calculation`: Human-readable calculation string
- `value`: Computed result

Example trace for "1174 Pax @ $105.00":
```python
MatchTrace(
    pattern_name="per_person",
    matched_text="1174 Pax @ $105.00",
    extracted={"pax": 1174, "price": 105.0},
    calculation="1174 × $105.00",
    value=123270.0
)
```

## Unmatched Lines

New function `parse_pdf_with_traces()` returns:
```python
@dataclass
class ParseResult:
    event_order: EventOrder
    matched_lines: list[tuple[str, ParsedLineWithTrace]]  # (raw_text, parsed)
    unmatched_lines: list[str]  # Lines that didn't match any pattern
```

Lines are "unmatched" if:
- They're in a recognized section (food, beverage, etc.)
- They contain pricing-related keywords ($, @, Pax, Per, etc.)
- But no regex pattern matched

This filters out headers, blank lines, and non-pricing text.

## UI Components

### Sidebar Navigation

```python
page = st.sidebar.radio("Navigate", ["Reconciliation", "Parser Testing"])

if page == "Reconciliation":
    main()  # Existing 4-step wizard
else:
    render_parser_testing()
```

### Parser Testing Page

**Section 1: Upload**
- File uploader for PDF
- "Extract" button
- Show PDF name and extraction status

**Section 2: Matched Lines Table**

| Line Text | Pattern | Extracted | Calculation | Value | Category | Note |
|-----------|---------|-----------|-------------|-------|----------|------|
| 1174 Pax @ $105.00 | per_person | pax=1174, price=$105 | 1174 × $105 | $123,270 | food | [text input] |
| 8 Guards 11:00-16:30 @ $71 | hourly | guards=8, hours=5.5, rate=$71 | 8 × 5.5 × $71 | $3,124 | other | [text input] |

- Each row has a text input for notes
- Rows are expandable to show full matched text if truncated

**Section 3: Unmatched Lines**

Expandable section showing lines that look like they should have matched but didn't:
```
⚠️ 3 Unmatched Lines (in pricing sections)

- "Additional Staffing - TBC"
- "Corkage @ Market Rate"
- "Linen Upgrade (see attached quote)"
```

Each unmatched line also has a note field.

**Section 4: Actions**

- "Add to Feedback Log" — Saves current PDF's notes to session log
- "Download Feedback (N entries)" — Exports JSON
- "Clear Log" — Clears accumulated feedback

### Feedback Counter

Show running count of feedback entries in session: "Feedback Log: 12 entries from 3 PDFs"

## JSON Export Format

```json
{
  "exported_at": "2026-06-09T14:30:00Z",
  "session_summary": {
    "pdfs_processed": 3,
    "total_entries": 12,
    "matched_with_notes": 8,
    "unmatched_with_notes": 4
  },
  "entries": [
    {
      "pdf_name": "EO_2895.pdf",
      "line_text": "1174 Pax @ $105.00",
      "matched": true,
      "pattern": "per_person",
      "extracted": {"pax": 1174, "price": 105.0},
      "calculation": "1174 × $105.00",
      "value": 123270.0,
      "category": "food",
      "note": "Correct"
    },
    {
      "pdf_name": "EO_2895.pdf",
      "line_text": "Corkage @ Market Rate",
      "matched": false,
      "pattern": null,
      "extracted": null,
      "calculation": null,
      "value": null,
      "category": "beverage",
      "note": "Should flag as needs_manual_value, not ignore"
    }
  ]
}
```

## Session State

```python
# Parser testing state
st.session_state.pt_current_result: ParseResult | None
st.session_state.pt_current_pdf_name: str | None
st.session_state.pt_feedback_log: list[FeedbackEntry]
```

## Project Structure Changes

```
recon/
├── __init__.py
├── models.py           # Existing
├── parser.py           # Modified: add MatchTrace, parse_line_with_trace()
├── feedback.py         # NEW: FeedbackEntry, FeedbackLog, export_feedback_json()
├── builder.py          # Unchanged
├── reconciler.py       # Unchanged
└── delphi_adapter.py   # Unchanged

app.py                  # Modified: add sidebar, render_parser_testing()
```

## Testing

1. **Parser trace tests:** Verify each pattern returns correct trace metadata
2. **Unmatched line detection:** Verify pricing-like lines are captured when no pattern matches
3. **Feedback export:** Verify JSON structure is correct
4. **UI integration:** Manual testing with real PDFs

## Open Items

None — ready for implementation.
