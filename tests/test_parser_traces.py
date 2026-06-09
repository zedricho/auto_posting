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
