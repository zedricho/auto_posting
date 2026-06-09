"""Tests for reconciler."""

import pytest
from recon.models import CategoryTotals, WorksheetOutput, EventOrder
from recon.reconciler import reconcile, Discrepancy


@pytest.fixture
def sample_worksheet() -> WorksheetOutput:
    """Create a sample worksheet output."""
    return WorksheetOutput(
        event=EventOrder(
            pm_number="9353",
            beo_number="2895",
            event_name="Test Event",
            line_items=[],
        ),
        totals=[
            CategoryTotals(category="food", delphi_total=123466.00, opera_total=123466.00),
            CategoryTotals(category="beverage", delphi_total=81839.60, opera_total=76990.63),
            CategoryTotals(category="resource", delphi_total=1150.00, opera_total=1150.00),
        ],
        delphi_grand_total=206455.60,
        opera_grand_total=201606.63,
    )


class TestReconciler:
    def test_no_discrepancies_when_matching(self, sample_worksheet: WorksheetOutput):
        """No discrepancies when Delphi report matches exactly."""
        delphi_report = {
            "food": 123466.00,
            "beverage": 81839.60,
            "resource": 1150.00,
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 0

    def test_rounding_tolerance(self, sample_worksheet: WorksheetOutput):
        """Variances within 5 cents are ignored."""
        delphi_report = {
            "food": 123466.03,  # 3 cents off
            "beverage": 81839.60,
            "resource": 1150.00,
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 0

    def test_detects_variance(self, sample_worksheet: WorksheetOutput):
        """Detects variance above tolerance."""
        delphi_report = {
            "food": 123466.00,
            "beverage": 81839.60,
            "resource": 1000.00,  # 150 off
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 1
        assert discrepancies[0].category == "resource"
        assert discrepancies[0].expected == 1150.00
        assert discrepancies[0].posted == 1000.00
        assert discrepancies[0].variance == -150.00

    def test_missing_category_in_delphi(self, sample_worksheet: WorksheetOutput):
        """Detects category missing from Delphi report."""
        delphi_report = {
            "food": 123466.00,
            "beverage": 81839.60,
            # resource missing
        }
        discrepancies = reconcile(sample_worksheet, delphi_report)
        assert len(discrepancies) == 1
        assert discrepancies[0].category == "resource"
        assert discrepancies[0].posted == 0.0
        assert "not posted" in discrepancies[0].likely_cause.lower()
