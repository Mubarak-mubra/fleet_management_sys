"""Project service: CRUD, auto-code issuance, validation, cost report."""
from datetime import date

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


def test_delete_project_blocked_while_linked(make_project, make_vehicle, make_fuel):
    project = make_project()
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, project_id=project.id)
    with pytest.raises(ValueError, match="Cannot delete"):
        project_service.delete_project(project.id)


def test_delete_project_unlinked_succeeds(make_project):
    project = make_project()
    project_service.delete_project(project.id)
    with pytest.raises(LookupError):
        project_service.get_project(project.id)


def test_cost_report_sums_all_four_sources(make_project, make_vehicle, make_fuel, make_maintenance, make_expense, make_trip):
    project = make_project()
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, project_id=project.id, liters=100, cost_per_liter=2.0)
    make_maintenance(vehicle=vehicle, project_id=project.id, cost=250.0)
    make_expense(vehicle_id=None, project_id=project.id, amount=75.0)
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=40.0)
    # A record with no project must NOT be counted.
    make_fuel(vehicle=vehicle, liters=999, cost_per_liter=9.0)

    report = project_service.project_cost_report(project.id)

    assert report["fuel_total"] == 200.0
    assert report["fuel_liters"] == 100.0
    assert report["maintenance_total"] == 250.0
    assert report["expense_total"] == 75.0
    assert report["total"] == 525.0
    assert report["distance_km"] == 40.0
    assert report["cost_per_km"] == pytest.approx(13.125)
    assert len(report["fuel_logs"]) == 1


def test_cost_report_respects_date_window(make_project, make_vehicle, make_fuel):
    project = make_project()
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, project_id=project.id, fuel_date=date(2026, 1, 5), liters=50, cost_per_liter=1.0)
    make_fuel(vehicle=vehicle, project_id=project.id, fuel_date=date(2026, 2, 5), liters=60, cost_per_liter=1.0)

    february = project_service.project_cost_report(project.id, date_from="2026-02-01")
    assert february["fuel_total"] == 60.0
    january = project_service.project_cost_report(project.id, date_to="2026-01-31")
    assert january["fuel_total"] == 50.0


def test_resolve_project_blank_and_unknown(db, make_project):
    assert project_service.resolve_project("") is None
    assert project_service.resolve_project(None) is None
    p = make_project()
    assert project_service.resolve_project(str(p.id)).id == p.id
    with pytest.raises(ValueError, match="Project not found"):
        project_service.resolve_project("424242")
    with pytest.raises(ValueError, match="Project not found"):
        project_service.resolve_project("not-a-number")
