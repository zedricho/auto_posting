"""Tests for parser match trace functionality."""

import pytest
from recon.models import MatchTrace
from recon.parser import parse_line_with_trace


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


def test_parse_result_dataclass():
    """ParseResult dataclass can be instantiated."""
    from recon.models import EventOrder, MatchTrace
    from recon.parser import ParsedLine, ParseResult

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
