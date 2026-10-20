"""CSRF protection — proven by turning it back on.

`TestConfig.WTF_CSRF_ENABLED = False` so the other 400-odd tests don't each
mint a token. That means nothing in the main suite would catch CSRF silently
breaking. This module builds a second app with CSRF enabled and asserts the
guard rejects requests with a missing, forged, or mismatched token — and
accepts a real one scraped from the rendered form.
"""
import re

import pytest

from app import create_app
from app.models import User, VehicleType
from extensions import db as _db


@pytest.fixture()
def csrf_app():
    """A testing app with CSRF enforcement switched back on.

    The app context is opened only to build the schema and seed the admin,
    then CLOSED before the test runs. Holding one open across the test would
    make Flask's `g` (which lives on the app context) survive between
    requests — and Flask-WTF caches the CSRF token in `g`, so client A's
    token would leak into client B's render while never entering B's session,
    producing spurious 400s. In production Flask pushes a fresh app context
    per request, so this only bites tests.
    """
    app = create_app("testing")
    app.config["WTF_CSRF_ENABLED"] = True
    with app.app_context():
        _db.create_all()
        user = User(username="csrfadmin", role="admin", active=True)
        user.set_password("secretpass123")
        _db.session.add(user)
        # The vehicle payloads below post type "dump_truck"; since types are
        # user-registered, put one in the registry so the success path can
        # actually reach the database.
        _db.session.add(VehicleType(name="dump_truck"))
        _db.session.commit()
    yield app
    with app.app_context():
        _db.session.remove()
        _db.drop_all()


def _login(app, c):
    """Log in the way a browser would: scrape the token from the rendered
    login form first. Posting without it is refused — which is itself the
    proof that login CSRF is protected.

    Do NOT wrap this POST in an extra `app.app_context()`: the test client
    pushes its own, and a nested one makes Flask drop the session cookie, so
    the login silently doesn't stick.
    """
    token = _token_from("/auth/login", c)
    resp = c.post(
        "/auth/login",
        data={"username": "csrfadmin", "password": "secretpass123",
              "csrf_token": token},
    )
    assert resp.status_code == 302, (
        "login failed with CSRF on — got "
        f"{resp.status_code}: {resp.get_data(as_text=True)[:300]}"
    )


def _token_from(path, c):
    """Scrape a genuine csrf_token out of a rendered form."""
    body = c.get(path).get_data(as_text=True)
    match = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', body)
    assert match, f"no csrf_token input rendered on {path}"
    return match.group(1)


def _vehicle_payload(**overrides):
    data = {
        "name": "CSRF Vehicle",
        "plate_number": "GC-CSRF1",
        "vehicle_type": "dump_truck",      # valid enum value
        "status": "active",
        "year": "2021",
        "odometer": "0",
    }
    data.update(overrides)
    return data


def test_missing_token_is_rejected(csrf_app):
    c = csrf_app.test_client()
    _login(csrf_app, c)
    resp = c.post("/vehicles/new", data=_vehicle_payload())
    assert resp.status_code == 400

    from app.models import Vehicle

    with csrf_app.app_context():
        assert Vehicle.query.filter_by(plate_number="GC-CSRF1").count() == 0


def test_forged_token_is_rejected(csrf_app):
    c = csrf_app.test_client()
    _login(csrf_app, c)
    resp = c.post(
        "/vehicles/new",
        data={**_vehicle_payload(plate_number="GC-CSRF2"), "csrf_token": "not-a-real-token"},
    )
    assert resp.status_code == 400


def test_token_from_another_session_is_rejected(csrf_app):
    """A token lifted from a different session must not work here."""
    other = csrf_app.test_client()
    stolen = _token_from("/auth/login", other)   # other session, not logged in

    c = csrf_app.test_client()
    _login(csrf_app, c)
    resp = c.post(
        "/vehicles/new",
        data={**_vehicle_payload(plate_number="GC-CSRF3"), "csrf_token": stolen},
    )
    assert resp.status_code == 400


def test_valid_token_is_accepted(csrf_app):
    c = csrf_app.test_client()
    _login(csrf_app, c)
    token = _token_from("/vehicles/new", c)
    resp = c.post(
        "/vehicles/new",
        data={**_vehicle_payload(plate_number="GC-CSRF4"), "csrf_token": token},
    )
    assert resp.status_code == 302, resp.get_data(as_text=True)

    from app.models import Vehicle

    with csrf_app.app_context():
        assert Vehicle.query.filter_by(plate_number="GC-CSRF4").count() == 1


def test_delete_requires_token(csrf_app):
    """The small row-level delete forms are protected too, not just big forms."""
    c = csrf_app.test_client()
    _login(csrf_app, c)
    token = _token_from("/vehicles/new", c)

    with csrf_app.app_context():
        from app.models import Vehicle

        v = Vehicle(name="Doomed", plate_number="GC-DELT", vehicle_type="dump_truck",
                    status="active", year=2020, odometer=0)
        _db.session.add(v)
        _db.session.commit()
        vid = v.id

    # Without a token -> refused, record survives:
    assert c.post(f"/vehicles/{vid}/delete").status_code == 400
    with csrf_app.app_context():
        from app.models import Vehicle

        assert _db.session.get(Vehicle, vid) is not None

    # With a token -> allowed:
    resp = c.post(f"/vehicles/{vid}/delete", data={"csrf_token": token})
    assert resp.status_code == 302
    with csrf_app.app_context():
        from app.models import Vehicle

        assert _db.session.get(Vehicle, vid) is None


def test_login_form_carries_token(csrf_app):
    """Even the public login form is CSRF-protected (login CSRF is a real attack)."""
    c = csrf_app.test_client()
    assert 'name="csrf_token"' in c.get("/auth/login").get_data(as_text=True)


def test_get_requests_unaffected_by_csrf(csrf_app):
    """Reads must never demand a token."""
    c = csrf_app.test_client()
    _login(csrf_app, c)
    assert c.get("/vehicles/").status_code == 200
    assert c.get("/").status_code == 200
