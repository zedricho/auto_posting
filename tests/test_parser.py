"""Tests for PDF parser."""

import pytest
from recon.parser import extract_headers, parse_line, ParsedLine


class TestHeaderExtraction:
    def test_extract_pm_number(self):
        """Extract Posting Master number from text."""
        text = "Some header text\nPosting Master #: 9353\nMore text"
        headers = extract_headers(text)
        assert headers["pm_number"] == "9353"

    def test_extract_beo_number(self):
        """Extract BEO number from text."""
        text = "Event info\nBEO#: 2895\nDetails"
        headers = extract_headers(text)
        assert headers["beo_number"] == "2895"

    def test_extract_event_name(self):
        """Extract event name from Post As line."""
        text = "Header\nPost As: Ultimate Origin Lunch 2026\nMore"
        headers = extract_headers(text)
        assert headers["event_name"] == "Ultimate Origin Lunch 2026"

    def test_extract_event_date(self):
        """Extract event date."""
        text = "Info\nEvent Date: Fri 05 Jun 2026\nDetails"
        headers = extract_headers(text)
        assert headers["event_date"] == "Fri 05 Jun 2026"

    def test_missing_fields_return_none(self):
        """Missing fields return None, not error."""
        text = "Some random text with no headers"
        headers = extract_headers(text)
        assert headers["pm_number"] is None
        assert headers["beo_number"] is None


class TestLineParsing:
    def test_per_person_pattern(self):
        """Parse '1174 Pax @ $105.00' pattern."""
        line = "Plated Meal – 3 Courses 1174 Pax @ $105.00 Per Person"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "per_person"
        assert result.pax == 1174
        assert result.unit_price == 105.00
        assert result.value == 123270.00

    def test_per_unit_pattern(self):
        """Parse '2 @ $150.00 Per 8m piece' pattern."""
        line = "Red Carpet 2 @ $150.00 Per 8m piece"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "per_unit"
        assert result.qty == 2
        assert result.unit_price == 150.00
        assert result.value == 300.00

    def test_flat_event_pattern(self):
        """Parse '@ $320.00 For This Event' pattern."""
        line = "Labour surcharge – XXXX Cartons @ $320.00 For This Event"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "flat"
        assert result.value == 320.00

    def test_flat_single_at_pattern(self):
        """Parse '1 @ $2,702.63' flat pattern."""
        line = "XXXX Cartons 1 @ $2,702.63"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "flat"
        assert result.qty == 1
        assert result.unit_price == 2702.63
        assert result.value == 2702.63

    def test_security_hourly_pattern(self):
        """Parse security guard hours pattern."""
        line = "8 Guards from 11:00 - 16:30 @ $71.00 Per Hour"
        result = parse_line(line)
        assert result is not None
        assert result.basis == "hourly"
        assert result.guards == 8
        assert result.hours == 5.5
        assert result.unit_price == 71.00
        assert result.value == 3124.00

    def test_consumption_line(self):
        """Lines with 'on consumption' are flagged."""
        line = "Speaker & VIP Drinks (Green Room) on consumption"
        result = parse_line(line)
        assert result is not None
        assert result.money_type == "consumption"
        assert result.needs_manual_value is True
        assert result.value == 0.0

    def test_guest_expense_line(self):
        """Lines with 'at guest expense' are flagged as cash."""
        line = "Basic Spirits at guest expense"
        result = parse_line(line)
        assert result is not None
        assert result.money_type == "cash"
        assert result.posts_to == "delphi_only"
        assert result.needs_manual_value is True
        assert result.value == 0.0

    def test_unrecognized_line_returns_none(self):
        """Lines without recognized patterns return None."""
        line = "Some random text without pricing"
        result = parse_line(line)
        assert result is None
