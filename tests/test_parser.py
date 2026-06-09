"""Tests for PDF parser."""

import pytest
from recon.parser import extract_headers


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
