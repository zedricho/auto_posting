"""Feedback collection for parser refinement."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional, List, Set, Dict

from recon.models import MatchTrace


@dataclass
class FeedbackEntry:
    """User feedback on a parsed line."""
    pdf_name: str
    line_text: str
    match_trace: Optional[MatchTrace]  # None if line was unmatched
    category: Optional[str]
    note: str
    timestamp: str


@dataclass
class FeedbackLog:
    """Accumulated feedback across PDFs."""
    entries: List[FeedbackEntry] = field(default_factory=list)

    def add(self, entry: FeedbackEntry) -> None:
        """Add an entry to the log."""
        self.entries.append(entry)

    def clear(self) -> None:
        """Clear all entries."""
        self.entries.clear()

    def get_pdf_names(self) -> Set[str]:
        """Get unique PDF names in the log."""
        return {e.pdf_name for e in self.entries}


def export_feedback_json(log: FeedbackLog) -> str:
    """Export feedback log as JSON string."""
    matched_count = sum(1 for e in log.entries if e.match_trace is not None)
    unmatched_count = len(log.entries) - matched_count

    entries_data = []
    for entry in log.entries:
        entry_dict: Dict[str, Any] = {
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
