"""Authentication and authorisation — the guards must actually guard.

Route tests use an already-signed-in `client`, so they only prove the happy
path. This module covers the other side: anonymous users are turned away,
viewers cannot mutate, and role rules hold.
"""

import pytest

from app.models import User
from app.services import auth_service


# ---- anonymous access ------------------------------------------------------


def test_anonymous_is_redirected_to_login(anon_client):
    resp = anon_client.get("/")
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_anonymous_redirected_from_every_section(anon_client):
    for path in (
        "/",
        "/vehicles/",
        "/trips/",
        "/fuel/",
        "/maintenance/",
        "/expenses/",
        "/drivers/",
        "/more/",
        "/users/",
    ):
        resp = anon_client.get(path)
        assert resp.status_code == 302, f"{path} was reachable anonymously"
        assert "/auth/login" in resp.headers["Location"], path


def test_anonymous_cannot_post(anon_client):
    resp = anon_client.post(
        "/vehicles/new",
        data={"name": "x", "plate_number": "GC-HACK", "vehicle_type": "truck",
              "status": "active", "year": "2020", "odometer": "0"},
    )
    assert resp.status_code == 302
    assert "/auth/login" in resp.headers["Location"]


def test_login_page_is_public(anon_client):
    resp = anon_client.get("/auth/login")
    assert resp.status_code == 200
    assert "Sign in" in resp.get_data(as_text=True)


def test_login_page_drops_all_app_chrome(anon_client):
    """The sign-in form stands alone: no sidebar, navbar or tab bar.

    base.html wraps each chrome include in an overridable block, and
    auth/login.html empties all three so an anonymous visitor is not shown
    navigation they cannot use (every link would just bounce back here).
    """
    body = anon_client.get("/auth/login").get_data(as_text=True)
    assert 'class="sidebar"' not in body, "sidebar leaked onto the login page"
    assert 'class="navbar"' not in body, "navbar leaked onto the login page"
    assert 'class="bottomnav"' not in body, "bottom nav leaked onto the login page"
    assert 'class="auth-page"' in body, "auth-page body class missing (card would sit off-centre)"


def test_authenticated_pages_keep_their_chrome(client):
    """The bare shell is login-only; the app frame must not disappear."""
    for path in ("/", "/vehicles/", "/trips/", "/fuel/", "/more/"):
        body = client.get(path).get_data(as_text=True)
        assert 'class="sidebar"' in body, f"sidebar missing on {path}"
        assert 'class="navbar"' in body, f"navbar missing on {path}"
        assert 'class="bottomnav"' in body, f"bottom nav missing on {path}"
        assert 'class="auth-page"' not in body, f"auth-page class leaked onto {path}"


def test_error_pages_keep_their_chrome(client):
    """404 goes through base.html and is authenticated, so nav stays."""
    body = client.get("/definitely-not-a-real-page").get_data(as_text=True)
    assert 'class="bottomnav"' in body
    assert 'class="sidebar"' in body
    assert 'class="auth-page"' not in body


# ---- navbar user menu ------------------------------------------------------
# The navbar shows only an avatar circle; the name, role and Sign out button
# live in a popover that reveals on :hover (mouse) and :focus-within (tap or
# keyboard). Both selectors are required: a pure-hover menu would strand
# touch users with no way to sign out, and the project ships no inline JS.


def test_navbar_shows_only_the_avatar_circle(client):
    body = client.get("/").get_data(as_text=True)
    assert '<button type="button" class="user-avatar"' in body
    assert 'class="user-menu-pop"' in body
    # Exactly one "Sign out" control, and it sits inside the popover.
    assert body.count(">Sign out<") == 1
    pop = body.split('class="user-menu-pop"', 1)[1]
    assert ">Sign out<" in pop, "Sign out escaped the popover"


def test_navbar_popover_carries_identity_and_logout(client):
    body = client.get("/").get_data(as_text=True)
    pop = body.split('class="user-menu-pop"', 1)[1]
    assert "<b>admin</b>" in pop or "<b>" in pop, "display name missing"
    assert 'action="/auth/logout"' in pop
    assert 'name="csrf_token"' in pop, "logout form lost its CSRF token"


def test_user_menu_reveals_on_hover_and_on_focus(app):
    """Touch users cannot hover, so :focus-within must be a second trigger."""
    css = app.test_client().get("/static/css/style.css").get_data(as_text=True)
    assert ".user-menu:hover .user-menu-pop" in css
    assert ".user-menu:focus-within .user-menu-pop" in css
    # The popover is hidden at rest and shown by the two rules above.
    assert ".user-menu-pop {" in css
    # No inline JS backs this, per project convention.
    assert ".user-chip" not in css, "stale .user-chip CSS left behind"


def test_static_is_public(app):
    resp = app.test_client().get("/static/css/style.css")
    assert resp.status_code == 200


def test_next_param_round_trips(anon_client):
    resp = anon_client.get("/trips/?status=baxay")
    assert "/auth/login" in resp.headers["Location"]
    assert "next=" in resp.headers["Location"]


# ---- login -----------------------------------------------------------------


def test_valid_login_succeeds(app, make_user):
    make_user(username="abdi", password="hunter2222")
    c = app.test_client()
    resp = c.post("/auth/login", data={"username": "abdi", "password": "hunter2222"})
    assert resp.status_code == 302
    assert "/auth/login" not in resp.headers["Location"]


def test_wrong_password_rejected(app, make_user):
    make_user(username="abdi", password="hunter2222")
    c = app.test_client()
    resp = c.post("/auth/login", data={"username": "abdi", "password": "wrong-pass"})
    assert resp.status_code == 401
    assert "Invalid username or password" in resp.get_data(as_text=True)


def test_unknown_username_rejected_same_message(app, make_user):
    """Must not reveal whether the account exists (user enumeration)."""
    make_user(username="abdi", password="hunter2222")
    c = app.test_client()
    resp = c.post("/auth/login", data={"username": "ghost", "password": "whatever1"})
    assert resp.status_code == 401
    body = resp.get_data(as_text=True)
    assert "Invalid username or password" in body
    # No hint that 'ghost' simply isn't registered:
    assert "not found" not in body.lower()
    assert "no such" not in body.lower()


def test_disabled_account_rejected(app, make_user):
    make_user(username="fired", password="hunter2222", active=False)
    c = app.test_client()
    resp = c.post("/auth/login", data={"username": "fired", "password": "hunter2222"})
    assert resp.status_code == 401
    assert "disabled" in resp.get_data(as_text=True).lower()


def test_logout_clears_session(client):
    client.get("/")                      # sanity: still logged in
    resp = client.post("/auth/logout")
    assert resp.status_code == 302
    # Now anonymous again:
    assert client.get("/").status_code == 302


def test_login_while_authenticated_redirects_home(client):
    resp = client.get("/auth/login")
    assert resp.status_code == 302
    assert "/auth/login" not in resp.headers["Location"]


# ---- brute-force throttling ------------------------------------------------


def test_lockout_after_repeated_failures(app, make_user):
    auth_service.reset_throttle()
    make_user(username="bruted", password="hunter2222")
    c = app.test_client()
    for _ in range(auth_service.MAX_ATTEMPTS):
        c.post("/auth/login", data={"username": "bruted", "password": "nope12345"})
    # Even the CORRECT password is refused once locked out:
    resp = c.post("/auth/login", data={"username": "bruted", "password": "hunter2222"})
    assert resp.status_code == 401
    assert "Too many attempts" in resp.get_data(as_text=True)


def test_successful_login_resets_counter(app, make_user):
    auth_service.reset_throttle()
    make_user(username="okuser", password="hunter2222")
    c = app.test_client()
    c.post("/auth/login", data={"username": "okuser", "password": "wrong1234"})
    c.post("/auth/login", data={"username": "okuser", "password": "hunter2222"})
    # Counter cleared -> a later failure starts fresh, no lockout message.
    resp = c.post("/auth/login", data={"username": "okuser", "password": "wrong1234"})
    assert "Too many attempts" not in resp.get_data(as_text=True)


# ---- authorisation by role -------------------------------------------------


def test_viewer_can_read(client, make_vehicle):
    make_vehicle()
    assert client.get("/vehicles/").status_code == 200


def test_viewer_cannot_create(viewer_client):
    resp = viewer_client.post(
        "/vehicles/new",
        data={"name": "Nope", "plate_number": "GC-NOPE", "vehicle_type": "truck",
              "status": "active", "year": "2020", "odometer": "0"},
    )
    assert resp.status_code == 403


def test_viewer_cannot_delete(viewer_client, make_vehicle):
    vehicle = make_vehicle()
    resp = viewer_client.post(f"/vehicles/{vehicle.id}/delete")
    assert resp.status_code == 403
    assert vehicle is not None


def test_operator_can_create(client):
    resp = client.post(
        "/vehicles/new",
        data={"name": "New Truck", "plate_number": "GC-OPR1", "vehicle_type": "truck",
              "status": "active", "year": "2021", "odometer": "0"},
    )
    assert resp.status_code == 302


def test_operator_cannot_manage_users(app, make_user):
    """Account management is admin-only even for writers."""
    user = make_user(username="ops1", role="operator")
    c = app.test_client()
    with app.app_context():
        c.post("/auth/login", data={"username": "ops1", "password": "secretpass123"})
    resp = c.get("/users/")
    assert resp.status_code == 403


def test_admin_can_manage_users(make_user, app):
    admin = make_user(username="root", role="admin")
    c = app.test_client()
    with app.app_context():
        c.post("/auth/login", data={"username": "root", "password": "secretpass123"})
    assert c.get("/users/").status_code == 200


# ---- password rules --------------------------------------------------------


def test_short_password_rejected(db):
    with pytest.raises(ValueError, match="at least 8"):
        auth_service.create_user({"username": "newuser", "password": "short"})


def test_duplicate_username_rejected(db, make_user):
    make_user(username="taken")
    with pytest.raises(ValueError, match="already taken"):
        auth_service.create_user({"username": "TAKEN", "password": "longenough1"})


def test_password_is_hashed_not_stored(make_user):
    user = make_user(username="hasher", password="hunter2222")
    assert "hunter2222" not in user.password_hash
    assert user.password_hash.startswith("scrypt")
    assert user.check_password("hunter2222")
    assert not user.check_password("hunter2223")


def test_last_admin_cannot_demote_self(client, make_user):
    """The only admin must not be able to strip their own admin role."""
    from app.services import auth_service as svc

    admin = svc.find_by_username("admin")
    with pytest.raises(ValueError, match="your own admin role"):
        svc.update_user(admin.id, {"role": "viewer"}, actor=admin)


def test_last_admin_cannot_be_deleted(app, make_user):
    from app.services import auth_service as svc

    only = make_user(username="lonely", role="admin")
    with pytest.raises(ValueError, match="admin account must remain"):
        svc.delete_user(only.id, actor=None)
