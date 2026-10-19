import warnings
from datetime import datetime

from sqlalchemy import event
from sqlalchemy.engine import Engine

from app import create_app
from app.models.base import utcnow
from app.services import vehicle_service
from extensions import db


def test_utcnow_naive_and_deprecation_free():
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = utcnow()
    assert isinstance(result, datetime)
    assert result.tzinfo is None


def test_vehicle_options_matches_legacy_dropdown(app, make_vehicle):
    make_vehicle(status="active", name="Alpha Mixer", plate_number="GC-Z001")
    make_vehicle(status="retired", name="Beta Truck", plate_number="GC-Z002")
    make_vehicle(status="maintenance", name="Alpha Loader", plate_number="GC-Z003")
    make_vehicle(status="active", name="Gamma Dozer", plate_number="GC-Z004")
    make_vehicle(status="retired", name="Alpha Dozer", plate_number="GC-Z005")
    make_vehicle(status="maintenance", name="Beta Mixer", plate_number="GC-Z006")

    new = vehicle_service.vehicle_options()
    legacy, _, _ = vehicle_service.list_vehicles(per_page=10_000)

    assert [(v.id, v.plate_number, v.name) for v in new] == [
        (v.id, v.plate_number, v.name) for v in legacy
    ]


def test_vehicle_options_single_statement_without_count(app, make_vehicle):
    make_vehicle(status="active", name="Alpha", plate_number="GC-S001")
    make_vehicle(status="retired", name="Zeta", plate_number="GC-S002")
    make_vehicle(status="maintenance", name="Mid", plate_number="GC-S003")

    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(Engine, "before_cursor_execute", before_cursor_execute)
    try:
        vehicle_service.vehicle_options()
    finally:
        event.remove(Engine, "before_cursor_execute", before_cursor_execute)

    assert len(statements) == 1, statements
    assert "count(" not in statements[0].lower(), statements


def test_500_handler_renders_error_template(app):
    # The route must be registered BEFORE the first request — Flask refuses
    # new routes once the app has handled one (the client fixture logs in
    # first, which would trip that check).
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/boom")
    def boom():
        raise RuntimeError("boom for test")

    c = app.test_client()
    with app.app_context():
        from app.models import User

        user = User(username="hardening500", role="admin", active=True)
        user.set_password("secretpass123")
        db.session.add(user)
        db.session.commit()
        c.post("/auth/login", data={"username": "hardening500", "password": "secretpass123"})

    resp = c.get("/boom")
    assert resp.status_code == 500
    body = resp.get_data(as_text=True)
    assert "500 — Server error" in body


def test_404_handler_renders_error_template(client):
    resp = client.get("/no-such-page-for-test")
    assert resp.status_code == 404
    body = resp.get_data(as_text=True)
    assert "404 — Page not found" in body
