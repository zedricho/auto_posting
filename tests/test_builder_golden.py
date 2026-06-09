"""Golden test: Builder must reproduce BEO 2895 totals exactly."""

import json
from pathlib import Path
import pytest
from recon.models import EventOrder
from recon.builder import compute_totals


@pytest.fixture
def beo_2895() -> EventOrder:
    """Load the golden fixture."""
    fixture_path = Path(__file__).parent / "fixtures" / "beo_2895.json"
    data = json.loads(fixture_path.read_text())
    return EventOrder.model_validate(data)


class TestGoldenBEO2895:
    """These targets come from the EO Reading Library spec."""

    def test_opera_grand_total(self, beo_2895: EventOrder):
        """Opera total must be exactly 205,230.63 (excludes cash)."""
        result = compute_totals(beo_2895)
        assert result.opera_grand_total == 205230.63

    def test_delphi_grand_total(self, beo_2895: EventOrder):
        """Delphi total must be exactly 210,079.60 (includes cash)."""
        result = compute_totals(beo_2895)
        assert result.delphi_grand_total == 210079.60

    def test_food_totals(self, beo_2895: EventOrder):
        """Food: 123,466.00 for both (no cash in food)."""
        result = compute_totals(beo_2895)
        food = next(t for t in result.totals if t.category == "food")
        assert food.delphi_total == 123466.00
        assert food.opera_total == 123466.00

    def test_beverage_totals(self, beo_2895: EventOrder):
        """Beverage: Delphi 81,839.60 (incl cash), Opera 76,990.63 (excl cash)."""
        result = compute_totals(beo_2895)
        bev = next(t for t in result.totals if t.category == "beverage")
        assert bev.delphi_total == 81839.60
        assert bev.opera_total == 76990.63

    def test_resource_totals(self, beo_2895: EventOrder):
        """Resource: 1,150.00 for both."""
        result = compute_totals(beo_2895)
        res = next(t for t in result.totals if t.category == "resource")
        assert res.delphi_total == 1150.00
        assert res.opera_total == 1150.00

    def test_other_totals(self, beo_2895: EventOrder):
        """Other (Security): 3,124.00 for both."""
        result = compute_totals(beo_2895)
        other = next(t for t in result.totals if t.category == "other")
        assert other.delphi_total == 3124.00
        assert other.opera_total == 3124.00

    def test_venue_hire_totals(self, beo_2895: EventOrder):
        """Venue Hire: 500.00 for both."""
        result = compute_totals(beo_2895)
        vh = next(t for t in result.totals if t.category == "venue_hire")
        assert vh.delphi_total == 500.00
        assert vh.opera_total == 500.00
