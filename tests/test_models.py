import pytest
from datetime import date
from recon.models import LineItem, EventOrder, CategoryTotals, WorksheetOutput


class TestLineItem:
    def test_contracted_line_item(self):
        """A contracted line with @ pricing posts to both systems."""
        item = LineItem(
            category="food",
            type="Plated Meal - 3 Courses",
            basis="per_person",
            pax=1174,
            unit_price=105.00,
            value=123270.00,
            money_type="contracted",
            posts_to="both",
        )
        assert item.category == "food"
        assert item.value == 123270.00
        assert item.needs_manual_value is False

    def test_cash_line_needs_manual_value(self):
        """A cash line (guest expense) needs manual value entry."""
        item = LineItem(
            category="beverage",
            type="Basic Spirits at Guest Expense",
            basis="guest_expense",
            value=0.0,
            money_type="cash",
            posts_to="delphi_only",
            needs_manual_value=True,
        )
        assert item.money_type == "cash"
        assert item.posts_to == "delphi_only"
        assert item.needs_manual_value is True

    def test_consumption_line_needs_manual_value(self):
        """A consumption line needs manual value entry."""
        item = LineItem(
            category="beverage",
            type="Speaker & VIP Drinks (Green Room)",
            basis="consumption",
            value=0.0,
            money_type="consumption",
            posts_to="both",
            needs_manual_value=True,
        )
        assert item.money_type == "consumption"
        assert item.posts_to == "both"
        assert item.needs_manual_value is True


class TestEventOrder:
    def test_event_order_with_line_items(self):
        """EventOrder holds metadata and line items."""
        event = EventOrder(
            pm_number="9353",
            beo_number="2895",
            event_name="Ultimate Origin Lunch 2026",
            event_date=date(2026, 6, 5),
            line_items=[
                LineItem(
                    category="food",
                    type="Plated Meal - 3 Courses",
                    basis="per_person",
                    pax=1174,
                    unit_price=105.00,
                    value=123270.00,
                    money_type="contracted",
                    posts_to="both",
                ),
            ],
        )
        assert event.pm_number == "9353"
        assert event.beo_number == "2895"
        assert len(event.line_items) == 1
        assert event.line_items[0].value == 123270.00
