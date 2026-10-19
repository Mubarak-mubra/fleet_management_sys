"""Expense routes — list, create, edit, delete, filters.

Uses the flash-reading pattern documented in tests/test_routes.py:
POST without follow_redirects -> assert 302 -> GET Location -> assert message.
"""

from datetime import date

from app.models import Expense


def test_list_empty(client):
    resp = client.get("/expenses/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "No expenses yet." in body


def test_list_shows_seeded_expenses(app, client):
    app.test_cli_runner().invoke(args=["seed-db"])
    resp = client.get("/expenses/")
    body = resp.get_data(as_text=True)
    assert "Fleet insurance premium" in body
    assert "Expenses" in body


def test_create_get_renders_form(client):
    resp = client.get("/expenses/new")
    assert resp.status_code == 200
    assert "New expense" in resp.get_data(as_text=True)


def test_create_post_redirects_and_persists(client, db):
    resp = client.post(
        "/expenses/new",
        data={
            "expense_date": "2026-09-10",
            "description": "Site parking",
            "amount": "25.00",
            "category": "parking",
        },
    )
    assert resp.status_code == 302

    follow = client.get(resp.headers["Location"])
    assert "Expense of 25.0 created" in follow.get_data(as_text=True)

    expense = Expense.query.filter_by(description="Site parking").one()
    assert expense.amount == 25.0
    assert expense.category == "parking"
    assert expense.vehicle_id is None


def test_create_with_vehicle(client, make_vehicle):
    vehicle = make_vehicle()
    resp = client.post(
        "/expenses/new",
        data={
            "expense_date": "2026-09-10",
            "description": "Toll",
            "amount": "6.50",
            "vehicle_id": vehicle.id,
            "category": "toll",
        },
    )
    assert resp.status_code == 302
    expense = Expense.query.filter_by(description="Toll").one()
    assert expense.vehicle_id == vehicle.id


def test_create_missing_fields_flashes_error(client, db):
    resp = client.post(
        "/expenses/new",
        data={"expense_date": "", "description": "", "amount": ""},
    )
    assert resp.status_code == 302

    follow = client.get(resp.headers["Location"])
    assert "Expense date is required" in follow.get_data(as_text=True)
    assert Expense.query.count() == 0


def test_create_negative_amount_flashes_error(client, db):
    resp = client.post(
        "/expenses/new",
        data={"expense_date": "2026-09-10", "description": "x", "amount": "-5"},
    )
    assert resp.status_code == 302

    follow = client.get(resp.headers["Location"])
    assert "Amount cannot be negative" in follow.get_data(as_text=True)
    assert Expense.query.count() == 0


def test_edit_get_prefills(client, make_expense):
    expense = make_expense(description="Original", amount=10)
    resp = client.get(f"/expenses/{expense.id}/edit")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Original" in body
    assert "Edit expense" in body


def test_edit_post_updates(client, make_expense):
    expense = make_expense(description="Original", amount=10)
    resp = client.post(
        f"/expenses/{expense.id}/edit",
        data={
            "expense_date": "2026-09-10",
            "description": "Updated",
            "amount": "99.00",
            "category": "office",
        },
    )
    assert resp.status_code == 302

    follow = client.get(resp.headers["Location"])
    assert "Expense updated" in follow.get_data(as_text=True)

    db_expense = Expense.query.get(expense.id)
    assert db_expense.description == "Updated"
    assert db_expense.amount == 99.0
    assert db_expense.category == "office"


def test_edit_unknown_returns_404(client):
    resp = client.post(
        "/expenses/9999/edit", data={"expense_date": "2026-09-10", "description": "x", "amount": "1"}
    )
    assert resp.status_code == 404


def test_delete_post_removes_and_flashes(client, make_expense):
    expense = make_expense()
    resp = client.post(f"/expenses/{expense.id}/delete")
    assert resp.status_code == 302

    follow = client.get(resp.headers["Location"])
    assert "Expense deleted" in follow.get_data(as_text=True)
    assert Expense.query.get(expense.id) is None


def test_delete_unknown_returns_404(client):
    resp = client.post("/expenses/9999/delete")
    assert resp.status_code == 404


def test_delete_is_post_only(client, make_expense):
    expense = make_expense()
    resp = client.get(f"/expenses/{expense.id}/delete")
    assert resp.status_code == 405
    assert Expense.query.get(expense.id) is not None


def test_filter_by_category(client, make_expense):
    make_expense(description="ZULU insurance premium", category="insurance", amount=100)
    make_expense(description="ZULU parking fee", category="parking", amount=10)

    resp = client.get("/expenses/?category=insurance")
    body = resp.get_data(as_text=True)
    assert "ZULU insurance premium" in body
    assert "ZULU parking fee" not in body


def test_filter_by_vehicle(client, make_vehicle, make_expense):
    v1 = make_vehicle()
    v2 = make_vehicle(plate_number="GC-OTHER")
    make_expense(vehicle=v1, description="For V1")
    make_expense(vehicle=v2, description="For V2")

    resp = client.get(f"/expenses/?vehicle_id={v1.id}")
    body = resp.get_data(as_text=True)
    assert "For V1" in body
    assert "For V2" not in body


def test_filter_by_date_range(client, make_expense):
    make_expense(expense_date=date(2026, 9, 1), description="Sept")
    make_expense(expense_date=date(2026, 10, 15), description="Oct")

    resp = client.get("/expenses/?date_from=2026-10-01")
    body = resp.get_data(as_text=True)
    assert "Oct" in body
    assert "Sept" not in body


def test_bad_filter_flashes_error(client):
    resp = client.get("/expenses/?date_from=not-a-date")
    assert resp.status_code == 200
    assert "Invalid date_from" in resp.get_data(as_text=True)


def test_list_shows_stats_total(client, make_expense):
    make_expense(amount=100, category="office")
    make_expense(amount=50, category="parking")
    resp = client.get("/expenses/")
    body = resp.get_data(as_text=True)
    assert "$150.00" in body


def test_expense_links_into_sidebar_and_more(app, client):
    resp = client.get("/more/")
    body = resp.get_data(as_text=True)
    assert "/expenses/" in body
