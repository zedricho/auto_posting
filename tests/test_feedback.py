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
