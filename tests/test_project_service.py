"""Project service: CRUD, auto-code issuance, validation, cost report."""
from datetime import date, datetime

import pytest

from app.services import project_service


def test_create_project_auto_issues_code(db):
    p1 = project_service.create_project({"name": "Ring Road"})
    p2 = project_service.create_project({"name": "Bridge Job"})
    assert p1.code == "PRJ-0001"
    assert p2.code == "PRJ-0002"


def test_create_project_accepts_manual_code(db):
    p = project_service.create_project({"name": "Manual", "code": "job-77"})
    assert p.code == "JOB-77"  # normalised to upper case


def test_create_project_rejects_duplicate_code_case_insensitive(db):
    project_service.create_project({"name": "A", "code": "PRJ-100"})
    with pytest.raises(ValueError, match="already exists"):
        project_service.create_project({"name": "B", "code": "prj-100"})


def test_create_project_requires_name(db):
    with pytest.raises(ValueError, match="name is required"):
        project_service.create_project({"name": "  "})


def test_create_project_rejects_invalid_status(db):
    with pytest.raises(ValueError, match="Invalid project status"):
        project_service.create_project({"name": "X", "status": "banana"})


def test_create_project_rejects_end_before_start(db):
    with pytest.raises(ValueError, match="cannot be before"):
        project_service.create_project(
            {"name": "X", "start_date": "2026-05-01", "end_date": "2026-04-01"}
        )


def test_update_project_roundtrip(make_project):
    p = make_project(name="Old", status="planned")
    updated = project_service.update_project(
        p.id,
        {"name": "New", "status": "completed", "client": "Ministry", "end_date": "2026-12-31"},
    )
    assert updated.name == "New"
    assert updated.status == "completed"
    assert updated.client == "Ministry"
    assert updated.code == p.code  # unchanged code is preserved


def test_update_project_keeps_code_when_blank(make_project):
    p = make_project(code="PRJ-500")
    updated = project_service.update_project(p.id, {"code": ""})
    assert updated.code == "PRJ-500"


def test_get_project_unknown_raises_lookup(db):
    with pytest.raises(LookupError):
        project_service.get_project(99999)


def test_list_projects_filters_by_status_and_search(make_project):
    project_service.create_project({"name": "Ring Road", "status": "active"})
    project_service.create_project({"name": "Bridge", "status": "completed", "client": "Acme"})
    active, total, _ = project_service.list_projects(status="active")
    assert total == 1
    assert active[0].name == "Ring Road"
    hits, total, _ = project_service.list_projects(q="acme")  # client matches
    assert total == 1
    assert hits[0].name == "Bridge"


def test_delete_project_blocked_while_linked(make_project, make_vehicle, make_trip):
    """A trip is what still links — fuel and maintenance no longer can."""
    project = make_project()
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, project_id=project.id)
    with pytest.raises(ValueError, match="Cannot delete"):
        project_service.delete_project(project.id)


def test_delete_project_unlinked_succeeds(make_project):
    project = make_project()
    project_service.delete_project(project.id)
    with pytest.raises(LookupError):
        project_service.get_project(project.id)


def test_cost_report_derives_fuel_from_trips_and_efficiency(
    make_project, make_vehicle, make_fuel, make_maintenance, make_expense, make_trip
):
    project = make_project()
    vehicle = make_vehicle()

    # Two fill-ups a measured 200 km apart, 50 L each: a real 4 km/L.
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=50, cost_per_liter=2.0, odometer=1000.0)
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 10), liters=50, cost_per_liter=2.0, odometer=1200.0)

    # 40 km of it on this project, 40 km elsewhere: the project's share is half.
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=40.0)
    make_trip(vehicle=vehicle, distance_km=40.0)
    make_maintenance(vehicle=vehicle, cost=250.0)
    make_expense(vehicle_id=None, project_id=project.id, amount=75.0)

    report = project_service.project_cost_report(project.id)

    # 40 km here at the vehicle's own 4 km/L = 10 L, at the fleet's 2.0/L.
    assert report["fuel_liters"] == pytest.approx(10.0)
    assert report["fuel_total"] == pytest.approx(20.0)
    # Half of this vehicle's 250 maintenance, because half its km were here.
    assert report["maintenance_total"] == pytest.approx(125.0)
    assert report["expense_total"] == 75.0
    assert report["total"] == pytest.approx(220.0)
    assert report["distance_km"] == 40.0
    assert report["cost_per_km"] == pytest.approx(5.5)
    # Fuel is never metered to a project, so it is always an estimate.
    assert report["fuel_estimate"] is True
    assert report["maintenance_estimate"] is True
    # The trip done elsewhere is not charged here — that is the whole point.
    assert len(report["vehicle_rows"]) == 1
    assert report["vehicle_rows"][0]["km"] == 40.0
    assert report["vehicle_rows"][0]["km_per_liter"] == pytest.approx(4.0)


def test_cost_report_falls_back_to_fleet_average_efficiency(
    make_project, make_vehicle, make_fuel, make_trip
):
    """A vehicle with no measured km/L still gets charged, at the fleet rate."""
    project = make_project()
    measured = make_vehicle()
    blind = make_vehicle()

    # Only `measured` has a usable fill-to-fill pair, at 4 km/L and 2.0/L.
    make_fuel(vehicle=measured, fuel_date=date(2026, 1, 1), liters=50, cost_per_liter=2.0, odometer=1000.0)
    make_fuel(vehicle=measured, fuel_date=date(2026, 1, 10), liters=50, cost_per_liter=2.0, odometer=1200.0)
    # `blind` has no odometer on any fill-up, so it produces no km/L.
    make_fuel(vehicle=blind, fuel_date=date(2026, 1, 5), liters=200, cost_per_liter=2.0)

    make_trip(vehicle=measured, project_id=project.id, distance_km=40.0)
    make_trip(vehicle=blind, project_id=project.id, distance_km=80.0)

    report = project_service.project_cost_report(project.id)

    # The fleet average only counts vehicles that produced a usable interval,
    # so here it is measured's own 4 km/L: blind gets 80/4 = 20 L.
    # measured: 40/4 = 10 L. Total 30 L, at the fleet's 2.0/L = 60.0.
    assert report["fuel_liters"] == pytest.approx(30.0)
    assert report["fuel_total"] == pytest.approx(60.0)

    rows = {row["vehicle"].id: row for row in report["vehicle_rows"]}
    assert rows[blind.id]["estimated_efficiency"] is True
    assert rows[measured.id]["estimated_efficiency"] is False


def test_cost_report_maintenance_share_is_capped_at_100(
    make_project, make_vehicle, make_maintenance, make_trip
):
    """A vehicle doing all its km here carries all of its maintenance here."""
    project = make_project()
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=100.0)
    make_maintenance(vehicle=vehicle, cost=250.0)

    report = project_service.project_cost_report(project.id)
    assert report["maintenance_total"] == pytest.approx(250.0)


def test_cost_report_respects_date_window(make_project, make_vehicle, make_expense, make_trip):
    project = make_project()
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=40.0,
              start_time=datetime(2026, 1, 5, 8, 0))
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=60.0,
              start_time=datetime(2026, 2, 5, 8, 0))
    make_expense(vehicle_id=None, project_id=project.id, amount=10.0,
                 expense_date=date(2026, 1, 6))
    make_expense(vehicle_id=None, project_id=project.id, amount=20.0,
                 expense_date=date(2026, 2, 6))

    february = project_service.project_cost_report(project.id, date_from="2026-02-01")
    assert february["distance_km"] == 60.0
    assert february["expense_total"] == 20.0

    january = project_service.project_cost_report(project.id, date_to="2026-01-31")
    assert january["distance_km"] == 40.0
    assert january["expense_total"] == 10.0


def test_resolve_project_blank_and_unknown(db, make_project):
    assert project_service.resolve_project("") is None
    assert project_service.resolve_project(None) is None
    p = make_project()
    assert project_service.resolve_project(str(p.id)).id == p.id
    with pytest.raises(ValueError, match="Project not found"):
        project_service.resolve_project("424242")
    with pytest.raises(ValueError, match="Project not found"):
        project_service.resolve_project("not-a-number")
