"""Builder: compute category totals and generate worksheet."""

from collections import defaultdict
from recon.models import EventOrder, CategoryTotals, WorksheetOutput


def compute_totals(event: EventOrder) -> WorksheetOutput:
    """
    Compute Delphi and Opera totals from an EventOrder.

    - Delphi total = all lines (contracted + consumption + cash)
    - Opera total = exclude cash (only contracted + consumption)
    """
    # Group line items by category
    by_category: dict[str, list] = defaultdict(list)
    for item in event.line_items:
        by_category[item.category].append(item)

    totals = []
    for category, items in by_category.items():
        # Delphi = all lines
        delphi_total = sum(item.value for item in items)

        # Opera = exclude cash (money_type != "cash")
        opera_total = sum(
            item.value for item in items if item.money_type != "cash"
        )

        totals.append(
            CategoryTotals(
                category=category,
                delphi_total=round(delphi_total, 2),
                opera_total=round(opera_total, 2),
            )
        )

    # Sort totals by category for consistent output
    category_order = ["food", "beverage", "resource", "other", "venue_hire", "av"]
    totals.sort(key=lambda t: category_order.index(t.category) if t.category in category_order else 99)

    return WorksheetOutput(
        event=event,
        totals=totals,
        delphi_grand_total=round(sum(t.delphi_total for t in totals), 2),
        opera_grand_total=round(sum(t.opera_total for t in totals), 2),
    )
