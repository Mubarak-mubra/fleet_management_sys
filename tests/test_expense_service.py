"""Expense recording — costs that are neither fuel nor maintenance.

Covers the service rules, the routes, the optional-vehicle design, and the
SET NULL behaviour that keeps money records alive when a vehicle is deleted.
"""

from datetime import date

import pytest

from app.models import Expense
from app.services import expense_service


# ---- create ----------------------------------------------------------------


def test_create_expense_minimal(db):
    e = expense_service.create_expense(
        {"expense_date": "2026-09-01", "description": "Parking", "amount": "18.50"}
    )
    assert e.amount == 18.50
    assert e.category == "other"          # default
    assert e.vehicle_id is None            # fleet-wide by default


def test_create_expense_with_vehicle(db, make_vehicle):
    vehicle = make_vehicle()
    e = expense_service.create_expense(
        {
            "expense_date": "2026-09-04",
            "description": "Yard parking",
            "amount": "18",
            "vehicle_id": vehicle.id,
            "category": "parking",
        }
    )
    assert e.vehicle_id == vehicle.id
    assert e.category == "parking"


def test_create_expense_requires_date(db):
    with pytest.raises(ValueError, match="date is required"):
        expense_service.create_expense({"description": "x", "amount": "1"})


def test_create_expense_requires_description(db):
    with pytest.raises(ValueError, match="Description is required"):
        expense_service.create_expense({"expense_date": "2026-09-01", "amount": "1"})


def test_create_expense_requires_amount(db):
    with pytest.raises(ValueError, match="Amount is required"):
        expense_service.create_expense({"expense_date": "2026-09-01", "description": "x"})


def test_create_expense_rejects_negative_amount(db):
    with pytest.raises(ValueError, match="cannot be negative"):
        expense_service.create_expense(
            {"expense_date": "2026-09-01", "description": "x", "amount": "-5"}
        )


def test_create_expense_zero_amount_allowed(db):
    """A zero-cost record (e.g. a warranty job) is still worth logging."""
    e = expense_service.create_expense(
        {"expense_date": "2026-09-01", "description": "Warranty work", "amount": "0"}
    )
    assert e.amount == 0.0


def test_create_expense_rejects_unknown_category(db):
    with pytest.raises(ValueError, match="Invalid expense category"):
        expense_service.create_expense(
            {"expense_date": "2026-09-01", "description": "x", "amount": "1",
             "category": "bribes"}
        )


def test_create_expense_rejects_unknown_vehicle(db):
    with pytest.raises(ValueError, match="Vehicle not found"):
        expense_service.create_expense(
            {"expense_date": "2026-09-01", "description": "x", "amount": "1",
             "vehicle_id": 9999}
        )


def test_blank_vehicle_means_fleet_wide(db):
    e = expense_service.create_expense(
        {"expense_date": "2026-09-01", "description": "Rent", "amount": "340",
         "vehicle_id": ""}
    )
    assert e.vehicle_id is None


# ---- update ----------------------------------------------------------------


def test_update_expense(db, make_expense):
    e = make_expense()
    updated = expense_service.update_expense(
        e.id, {"amount": "250", "description": "Adjusted", "category": "office"}
    )
    assert updated.amount == 250.0
    assert updated.description == "Adjusted"
    assert updated.category == "office"


def test_update_expense_rejects_negative_amount(db, make_expense):
    e = make_expense()
    with pytest.raises(ValueError, match="cannot be negative"):
        expense_service.update_expense(e.id, {"amount": "-1"})


def test_update_expense_can_detach_vehicle(db, make_expense, make_vehicle):
    e = make_expense(vehicle=make_vehicle())
    updated = expense_service.update_expense(e.id, {"vehicle_id": ""})
    assert updated.vehicle_id is None


def test_update_unknown_raises_lookup(db):
    with pytest.raises(LookupError):
        expense_service.update_expense(9999, {"amount": "1"})


# ---- list / filter ---------------------------------------------------------


def test_list_filters_by_vehicle_and_category(db, make_vehicle, make_expense):
    v1, v2 = make_vehicle(), make_vehicle(plate_number="GC-TEST2")
    make_expense(vehicle=v1, category="parking", amount=10)
    make_expense(vehicle=v2, category="fine", amount=20)
    make_expense(vehicle=None, category="office", amount=30)   # fleet-wide

    items, total, _ = expense_service.list_expenses(vehicle_id=v1.id)
    assert total == 1
    items, total, _ = expense_service.list_expenses(category="office")
    assert total == 1
    assert items[0].vehicle_id is None


def test_list_filters_by_date_range(db, make_expense):
    make_expense(expense_date=date(2026, 9, 1))
    make_expense(expense_date=date(2026, 10, 15))
    _, total, _ = expense_service.list_expenses(date_from="2026-10-01")
    assert total == 1
    _, total, _ = expense_service.list_expenses(date_to="2026-09-30")
    assert total == 1
    _, total, _ = expense_service.list_expenses(date_from="2026-09-01", date_to="2026-10-31")
    assert total == 2


def test_list_orders_newest_first(db, make_expense):
    make_expense(expense_date=date(2026, 9, 1), description="Old")
    make_expense(expense_date=date(2026, 10, 1), description="New")
    items, _, _ = expense_service.list_expenses()
    assert [i.description for i in items] == ["New", "Old"]


# ---- stats -----------------------------------------------------------------


def test_expense_stats_totals(db, make_expense):
    make_expense(amount=100, category="office")
    make_expense(amount=50, category="parking")
    make_expense(amount=25, category="parking")
    stats = expense_service.expense_stats()
    assert stats["total"] == 175.0
    assert stats["count"] == 3
    assert stats["by_category"] == {"office": 100.0, "parking": 75.0}


def test_expense_stats_respects_filters(db, make_vehicle, make_expense):
    v1, v2 = make_vehicle(), make_vehicle(plate_number="GC-TEST2")
    make_expense(vehicle=v1, amount=100)
    make_expense(vehicle=v2, amount=999)
    assert expense_service.expense_stats(vehicle_id=v1.id)["total"] == 100.0


# ---- deletion + SET NULL ---------------------------------------------------


def test_delete_expense(db, make_expense):
    e = make_expense()
    expense_service.delete_expense(e.id)
    assert Expense.query.get(e.id) is None


def test_delete_vehicle_keeps_expense(db, make_vehicle, make_expense):
    """The money was spent; deleting the vehicle must not erase the record."""
    vehicle = make_vehicle()
    e = make_expense(vehicle=vehicle)
    expense_service.delete_expense(e.id)  # sanity: fixture path works
    e2 = make_expense(vehicle=vehicle)

    db.session.delete(vehicle)
    db.session.commit()

    survivor = Expense.query.get(e2.id)
    assert survivor is not None, "expense must survive vehicle deletion"
    assert survivor.vehicle_id is None, "link should be nulled, not cascaded"
    assert survivor.amount == 100.0


def test_unknown_expense_raises_lookup(db):
    with pytest.raises(LookupError):
        expense_service.get_expense(9999)
