"""Monthly report service + routes."""
from datetime import date

import pytest

from app.services import report_service


def test_monthly_summary_groups_by_vehicle(make_vehicle, make_fuel, make_maintenance, make_expense):
    vehicle = make_vehicle(name="Grader")
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 9, 10), liters=100, cost_per_liter=2.0)
    make_maintenance(vehicle=vehicle, performed_date=date(2026, 9, 12), cost=300.0)
    make_expense(vehicle=vehicle, expense_date=date(2026, 9, 15), amount=50.0)
    # Out-of-month records must not leak in.
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 8, 10), liters=999, cost_per_liter=9.0)

    data = report_service.monthly_summary("2026-09")

    assert data["label"] == "September 2026"
    assert len(data["vehicles"]) == 1
    entry = data["vehicles"][0]
    assert entry["fuel"]["cost"] == 200.0
    assert entry["maintenance"]["cost"] == 300.0
    assert entry["expenses"]["cost"] == 50.0
    assert entry["total"] == 550.0
    assert data["grand_total"] == 550.0
    assert data["fuel_liters"] == 100.0


def test_monthly_summary_counts_fleet_wide_expenses(make_expense):
    make_expense(vehicle_id=None, expense_date=date(2026, 9, 2), amount=400.0, category="office")

    data = report_service.monthly_summary("2026-09")

    assert data["expense_total"] == 400.0
    assert data["unassigned_total"] == 400.0
    assert data["grand_total"] == 400.0
    assert data["expense_by_category"]["office"] == 400.0


def test_monthly_summary_prices_null_total_cost_fills(make_vehicle, make_fuel):
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 9, 5), liters=50, cost_per_liter=2.0, total_cost=None)

    data = report_service.monthly_summary("2026-09")

    assert data["fuel_total"] == 100.0  # liters x cost_per_liter fallback


def test_monthly_summary_counts_trips(make_vehicle, make_trip):
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, start_time=date(2026, 9, 3))
    make_trip(vehicle=vehicle, start_time=date(2026, 10, 1))

    data = report_service.monthly_summary("2026-09")
    assert data["trip_count"] == 1


def test_monthly_summary_rejects_bad_month(db):
    with pytest.raises(ValueError, match="2026-10"):
        report_service.monthly_summary("banana")


def test_monthly_summary_defaults_to_current_month(db):
    today = date.today()
    data = report_service.monthly_summary(None)
    assert (data["year"], data["month"]) == (today.year, today.month)


def test_monthly_report_page_renders(client, make_vehicle, make_fuel):
    vehicle = make_vehicle(name="Bulldozer B-12")
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 9, 10), liters=10, cost_per_liter=1.0)

    resp = client.get("/reports/monthly/?month=2026-09")

    assert resp.status_code == 200
    assert b"September 2026" in resp.data
    assert b"Bulldozer B-12" in resp.data


def test_monthly_report_bad_month_redirects(client):
    resp = client.get("/reports/monthly/?month=banana", follow_redirects=True)
    assert resp.status_code == 200
    assert b"Month must look like" in resp.data


def test_monthly_csv_download(client):
    resp = client.get("/reports/monthly/csv?month=2026-09")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "fleet-summary-2026-09.csv" in resp.headers["Content-Disposition"]
    assert b"GRAND TOTAL" in resp.data


def test_reports_require_login(anon_client):
    assert anon_client.get("/reports/monthly/").status_code == 302
    assert anon_client.get("/reports/monthly/csv").status_code == 302


def test_viewer_can_read_reports(viewer_client):
    assert viewer_client.get("/reports/monthly/").status_code == 200
    assert viewer_client.get("/reports/monthly/csv").status_code == 200
