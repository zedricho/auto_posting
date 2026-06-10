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


def test_parse_line_standalone_hourly_rate():
    """Standalone hourly rate (no guards/hours) returns trace with needs_manual_value."""
    result = parse_line_with_trace("@ $71.00 Per Hour")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "hourly_rate_only"
    assert trace.extracted["rate"] == 71.0
    assert "needs manual entry" in trace.calculation
    assert parsed.needs_manual_value is True
    assert parsed.unit_price == 71.0


def test_parse_line_standalone_per_unit():
    """Standalone per-unit price (no qty) returns trace with needs_manual_value."""
    result = parse_line_with_trace("@ $150.00 Per 8m piece")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "per_unit_rate_only"
    assert trace.extracted["price"] == 150.0
    assert "needs manual entry" in trace.calculation
    assert parsed.needs_manual_value is True
    assert parsed.unit_price == 150.0


def test_parse_line_schedule_rental():
    """Schedule table row with rental fee returns correct trace."""
    # Matches: HH:MM - HH:MM Function Name ... $X.XX
    result = parse_line_with_trace("11:00 - 11:30 VIP Meet & Greet Room Business Centre Cocktail 20 $500.00")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "schedule_rental"
    assert trace.extracted["price"] == 500.0
    # Function name should be cleaned (venue info removed)
    assert "VIP Meet & Greet Room" in trace.extracted["function"]
    assert "venue rental" in trace.calculation.lower()
    assert trace.value == 500.0
    assert parsed.basis == "flat"
    assert parsed.value == 500.0
    # GTD (20) should NOT multiply the price
    assert parsed.value == 500.0  # Not 20 * 500


def test_parse_line_schedule_rental_zero_price():
    """Schedule table row with $0 price should not match."""
    result = parse_line_with_trace("11:00 - 11:30 Main Event Brisbane Ballroom Theatre 1174 $0.00")
    # Should return None because price is 0
    assert result is None


def test_parse_line_day_delegate_package():
    """Day delegate package returns correct trace with per-person calculation."""
    result = parse_line_with_trace("$89 Half Day Executive Meeting Package AM 15 $89.00")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "day_package"
    assert trace.extracted["qty"] == 15
    assert trace.extracted["price_per_person"] == 89.0
    assert "Half Day" in trace.extracted["package"]
    assert trace.value == 1335.0  # 15 × $89
    assert parsed.basis == "per_person"
    assert parsed.pax == 15
    assert parsed.unit_price == 89.0
    assert parsed.value == 1335.0


def test_parse_line_day_delegate_package_full_day():
    """Full day package also matches the day package pattern."""
    result = parse_line_with_trace("Full Day Meeting Package 20 $150.00")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "day_package"
    assert trace.extracted["qty"] == 20
    assert trace.extracted["price_per_person"] == 150.0
    assert trace.value == 3000.0  # 20 × $150
    assert parsed.pax == 20


def test_day_package_has_is_package_flag():
    """Day delegate packages are flagged for splitting."""
    result = parse_line_with_trace("$89 Half Day Executive Meeting Package AM 15 $89.00")
    assert result is not None
    parsed, trace = result

    assert parsed.is_package is True
    assert "split" in trace.calculation.lower()


def test_schedule_rental_has_category_override():
    """Schedule table rentals have category_override to venue_hire."""
    result = parse_line_with_trace("10:00 - 14:00 Meeting New Farm Room Classroom 15 $1,456.00")
    assert result is not None
    parsed, trace = result

    assert parsed.category_override == "venue_hire"
    assert "venue_hire" in trace.calculation


def test_package_splits_constant():
    """Package splits add up to 100%."""
    from recon.parser import PACKAGE_SPLITS

    total = sum(PACKAGE_SPLITS.values())
    assert total == 1.0
    assert PACKAGE_SPLITS["food"] == 0.90
    assert PACKAGE_SPLITS["beverage"] == 0.05
    assert PACKAGE_SPLITS["resource"] == 0.05


def test_parse_line_barista_coffee():
    """Barista coffee orders are treated like consumption - manual entry after event."""
    result = parse_line_with_trace("Barista Coffee Orders")
    assert result is not None
    parsed, trace = result

    assert trace.pattern_name == "barista"
    assert "Manual entry" in trace.calculation
    assert parsed.basis == "consumption"
    assert parsed.needs_manual_value is True
    assert parsed.value == 0.0
    assert parsed.money_type == "consumption"
