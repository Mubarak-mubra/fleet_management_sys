"""Project routes: CRUD, cost report page, CSV export, auth + roles."""
from datetime import date


def test_projects_require_login(anon_client):
    resp = anon_client.get("/projects/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_project_list_renders_for_admin(client):
    resp = client.get("/projects/")
    assert resp.status_code == 200
    assert b"New project" in resp.data


def test_project_create_roundtrip(client, db):
    from app.models import Project

    resp = client.post(
        "/projects/new",
        data={"name": "Ring Road Extension", "client": "Ministry", "location": "Km12"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    project = Project.query.filter_by(name="Ring Road Extension").one()
    assert project.code == "PRJ-0001"
    assert project.status == "planned"
    assert b"Ring Road Extension" in resp.data


def test_project_create_validation_error_flashes(client, db):
    from app.models import Project

    resp = client.post("/projects/new", data={"name": ""}, follow_redirects=True)
    assert b"Project name is required" in resp.data
    assert Project.query.count() == 0


def test_project_edit_roundtrip(client, make_project):
    project = make_project(name="Old Name")
    resp = client.post(
        f"/projects/{project.id}/edit",
        data={"name": "New Name", "status": "completed", "code": project.code},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b"New Name" in resp.data
    assert project.status == "completed"


def test_project_delete_unlinked(client, make_project, db):
    project = make_project()
    resp = client.post(f"/projects/{project.id}/delete", follow_redirects=True)
    assert resp.status_code == 200
    from app.models import Project

    assert db.session.get(Project, project.id) is None


def test_project_delete_blocked_when_linked(client, make_project, make_vehicle, make_trip, db):
    project = make_project()
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, project_id=project.id)
    resp = client.post(f"/projects/{project.id}/delete", follow_redirects=True)
    assert b"Cannot delete" in resp.data
    from app.models import Project

    assert db.session.get(Project, project.id) is not None


def test_project_detail_shows_cost_totals(client, make_project, make_vehicle, make_fuel, make_trip):
    project = make_project(name="Cost Job")
    vehicle = make_vehicle()
    # A measured 4 km/L: 100 km apart, 25 L each fill.
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=25, cost_per_liter=2.0, odometer=1000.0)
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 11), liters=25, cost_per_liter=2.0, odometer=1100.0)
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=40.0)
    resp = client.get(f"/projects/{project.id}/")
    assert resp.status_code == 200
    assert b"Cost Job" in resp.data
    # 40 km at 4 km/L = 10 L, at the fleet's 2.0/L = $20.00, shown as an estimate.
    assert b"$20.00" in resp.data
    assert b"estimated" in resp.data.lower()


def test_project_detail_unknown_404(client):
    resp = client.get("/projects/99999/")
    assert resp.status_code == 404


def test_project_csv_download(client, make_project, make_vehicle, make_fuel, make_trip):
    project = make_project(name="CSV Job")
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=25, cost_per_liter=2.0, odometer=1000.0)
    make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 11), liters=25, cost_per_liter=2.0, odometer=1100.0)
    make_trip(vehicle=vehicle, project_id=project.id, distance_km=40.0)
    resp = client.get(f"/projects/{project.id}/csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.data.decode()
    assert "GRAND TOTAL" in body
    assert "20.00" in body
    # The estimate must be labelled as one in the export too.
    assert "fuel (estimate)" in body


def test_viewer_can_read_projects_but_not_write(viewer_client, make_project):
    project = make_project()
    assert viewer_client.get("/projects/").status_code == 200
    assert viewer_client.get(f"/projects/{project.id}/").status_code == 200
    assert viewer_client.get(f"/projects/{project.id}/csv").status_code == 200
    resp = viewer_client.post("/projects/new", data={"name": "Nope"})
    assert resp.status_code == 403
    resp = viewer_client.post(f"/projects/{project.id}/delete")
    assert resp.status_code == 403


def test_only_trip_and_expense_forms_render_project_dropdown(client, make_project):
    """Trips and expenses ask for a project; fuel and maintenance must not.

    Nobody at the pump can say which job a fill-up or a tyre belongs to, so
    those two forms must not offer the question at all.
    """
    make_project(name="Dropdown Job")

    for url in ("/trips/new", "/expenses/new"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert b'name="project_id"' in resp.data, url
        assert b"Dropdown Job" in resp.data, url

    for url in ("/fuel/new", "/maintenance/new"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert b'name="project_id"' not in resp.data, url


def test_expense_form_posts_project(client, make_project, make_vehicle, db):
    from app.models import Expense

    project = make_project()
    vehicle = make_vehicle()
    resp = client.post(
        "/expenses/new",
        data={
            "expense_date": "2026-09-01",
            "description": "Site guarding",
            "amount": "50",
            "vehicle_id": str(vehicle.id),
            "project_id": str(project.id),
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    expense = Expense.query.filter_by(description="Site guarding").one()
    assert expense.project_id == project.id
