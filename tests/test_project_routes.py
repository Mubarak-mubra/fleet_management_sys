"""Project routes: CRUD, cost report page, CSV export, auth + roles."""


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


def test_project_delete_blocked_when_linked(client, make_project, make_vehicle, make_fuel, db):
    project = make_project()
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, project_id=project.id)
    resp = client.post(f"/projects/{project.id}/delete", follow_redirects=True)
    assert b"Cannot delete" in resp.data
    from app.models import Project

    assert db.session.get(Project, project.id) is not None


def test_project_detail_shows_cost_totals(client, make_project, make_vehicle, make_fuel):
    project = make_project(name="Cost Job")
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, project_id=project.id, liters=80, cost_per_liter=2.0)
    resp = client.get(f"/projects/{project.id}/")
    assert resp.status_code == 200
    assert b"Cost Job" in resp.data
    assert b"$160.00" in resp.data  # fuel total rendered with currency filter


def test_project_detail_unknown_404(client):
    resp = client.get("/projects/99999/")
    assert resp.status_code == 404


def test_project_csv_download(client, make_project, make_vehicle, make_fuel):
    project = make_project(name="CSV Job")
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, project_id=project.id, liters=40, cost_per_liter=2.0)
    resp = client.get(f"/projects/{project.id}/csv")
    assert resp.status_code == 200
    assert resp.mimetype == "text/csv"
    assert "attachment" in resp.headers["Content-Disposition"]
    body = resp.data.decode()
    assert "GRAND TOTAL" in body
    assert "80.00" in body


def test_viewer_can_read_projects_but_not_write(viewer_client, make_project):
    project = make_project()
    assert viewer_client.get("/projects/").status_code == 200
    assert viewer_client.get(f"/projects/{project.id}/").status_code == 200
    assert viewer_client.get(f"/projects/{project.id}/csv").status_code == 200
    resp = viewer_client.post("/projects/new", data={"name": "Nope"})
    assert resp.status_code == 403
    resp = viewer_client.post(f"/projects/{project.id}/delete")
    assert resp.status_code == 403


def test_cost_forms_render_project_dropdown(client, make_project):
    make_project(name="Dropdown Job")
    for url in ("/fuel/new", "/trips/new", "/maintenance/new", "/expenses/new"):
        resp = client.get(url)
        assert resp.status_code == 200, url
        assert b'name="project_id"' in resp.data, url
        assert b"Dropdown Job" in resp.data, url


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
