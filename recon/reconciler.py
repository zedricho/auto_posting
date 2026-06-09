"""Reconciler: compare worksheet vs Delphi posting report."""

from dataclasses import dataclass
from recon.models import WorksheetOutput


ROUNDING_TOLERANCE = 0.05  # 5 cents


@dataclass
class Discrepancy:
    """A discrepancy between expected and posted values."""

    category: str
    expected: float
    posted: float
    variance: float
    likely_cause: str


def _diagnose_cause(
    category: str,
    expected: float,
    posted: float,
    variance: float,
    worksheet: WorksheetOutput,
) -> str:
    """
    Determine the likely cause of a discrepancy.

    Uses heuristics from the EO Reading Library spec.
    """
    abs_variance = abs(variance)

    # Check if variance matches a cash line value
    for item in worksheet.event.line_items:
        if item.money_type == "cash" and abs(abs_variance - item.value) < 1.0:
            return f"Cash sale ({item.type}) likely posted to Opera by mistake, or excluded from Delphi"

    # Check if variance matches a consumption line value
    for item in worksheet.event.line_items:
        if item.money_type == "consumption" and abs(abs_variance - item.value) < 1.0:
            return f"Consumption ({item.type}) not keyed, or keyed to wrong category"

    # Check for GST mismatch (variance ≈ 10% or 1/11 of expected)
    if expected > 0:
        ratio = abs_variance / expected
        if 0.09 < ratio < 0.11:
            return "GST treatment mismatch (inc vs ex GST)"
        if 0.085 < ratio < 0.095:  # 1/11 ≈ 0.0909
            return "GST treatment mismatch (inc vs ex GST)"

    # Check if variance equals a specific line's value
    for item in worksheet.event.line_items:
        if item.category == category and abs(abs_variance - item.value) < 1.0:
            return f"Line '{item.type}' appears not to have been posted"

    # Category missing entirely
    if posted == 0.0 and expected > 0:
        return f"Entire {category} category not posted"

    # Default
    return "Variance detected - manual review required"


def reconcile(
    worksheet: WorksheetOutput,
    delphi_report: dict[str, float],
) -> list[Discrepancy]:
    """
    Compare computed worksheet against Delphi posting report.

    Returns list of discrepancies (empty if all match within tolerance).
    """
    discrepancies: list[Discrepancy] = []

    for total in worksheet.totals:
        expected = total.delphi_total
        posted = delphi_report.get(total.category, 0.0)
        variance = posted - expected

        # Skip if within rounding tolerance
        if abs(variance) <= ROUNDING_TOLERANCE:
            continue

        cause = _diagnose_cause(
            category=total.category,
            expected=expected,
            posted=posted,
            variance=variance,
            worksheet=worksheet,
        )

        discrepancies.append(
            Discrepancy(
                category=total.category,
                expected=expected,
                posted=posted,
                variance=round(variance, 2),
                likely_cause=cause,
            )
        )

    return discrepancies
