"""Guards for the four production-readiness fixes.

1. The session cookie must carry a real expiry (PERMANENT_SESSION_LIFETIME is
   only enforced for *permanent* sessions).
2. A forged X-Forwarded-For must not change the login throttle key.
3. ProxyFix is installed only when TRUSTED_PROXY_HOPS says to trust a proxy.
4. Development and production open the SAME default database.
"""
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

from flask import request
from werkzeug.middleware.proxy_fix import ProxyFix

from app import _configure_proxy
from config import DEFAULT_DB_URI, DevConfig, ProdConfig, TestConfig
from app.services import auth_service


# ---- 1. session lifetime ----------------------------------------------------


def _expiry_of(response):
    """Parse the session cookie's Expires attribute, if it has one."""
    for header in response.headers.getlist("Set-Cookie"):
        if not header.startswith("session="):
            continue
        for part in header.split(";"):
            part = part.strip()
            if part.startswith("Expires="):
                return parsedate_to_datetime(part.split("=", 1)[1])
    return None


def test_session_cookie_has_a_real_expiry(app, make_user):
    """A signed-in session must not be a browser-session cookie.

    Without `session.permanent = True` Flask emits no Max-Age/Expires at all,
    so the configured 8-hour lifetime is silently ignored and the session
    lives until the browser closes.
    """
    make_user(username="permuser", password="secretpass123")
    c = app.test_client()
    resp = c.post(
        "/auth/login",
        data={"username": "permuser", "password": "secretpass123"},
    )
    assert resp.status_code == 302

    expires = _expiry_of(resp)
    assert expires is not None, "session cookie carries no expiry at all"

    lifetime = app.config["PERMANENT_SESSION_LIFETIME"]
    remaining = expires - datetime.now(expires.tzinfo)
    # Refreshed on each request, so it must land close to the configured
    # lifetime — and certainly nowhere near "never".
    assert timedelta(minutes=5) < remaining <= lifetime + timedelta(minutes=5)


def test_logout_forgets_the_session(app, make_user):
    """Logout must clear the identity even though a flash cookie is reissued."""
    make_user(username="permuser2", password="secretpass123")
    c = app.test_client()
    c.post("/auth/login", data={"username": "permuser2", "password": "secretpass123"})
    resp = c.post("/auth/logout")
    assert resp.status_code == 302
    # The re-issued cookie holds only the flash message, never the identity.
    for header in resp.headers.getlist("Set-Cookie"):
        if header.startswith("session="):
            assert "_user_id" not in header
    assert c.get("/vehicles/").status_code == 302  # back to anonymous


# ---- 2. login throttle vs forged headers ------------------------------------


def test_forged_forwarded_for_cannot_reset_throttle(app, make_user):
    """Each attempt spoofs a fresh IP; the lockout must still land."""
    auth_service.reset_throttle()
    make_user(username="bruted", password="hunter2222")
    c = app.test_client()
    for i in range(auth_service.MAX_ATTEMPTS):
        c.post(
            "/auth/login",
            data={"username": "bruted", "password": "nope12345"},
            headers={"X-Forwarded-For": f"203.0.113.{i}"},
        )
    resp = c.post(
        "/auth/login",
        data={"username": "bruted", "password": "hunter2222"},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert resp.status_code == 401
    assert "Too many attempts" in resp.get_data(as_text=True)
    auth_service.reset_throttle()


def _install_probe(app, make_user, path):
    """Register an authed probe route before the app handles any request."""
    seen = {}

    @app.route(path)
    def _probe():
        seen["ip"] = request.remote_addr
        return "ok"

    make_user(username="probe1", password="secretpass123")
    c = app.test_client()
    c.post("/auth/login", data={"username": "probe1", "password": "secretpass123"})
    return c, seen


def test_forwarded_for_is_ignored_without_a_proxy(app, make_user):
    """With no trusted proxy, remote_addr stays the real socket peer."""
    c, seen = _install_probe(app, make_user, "/_probe_remote_addr")
    resp = c.get("/_probe_remote_addr", headers={"X-Forwarded-For": "203.0.113.5"})
    assert resp.status_code == 200
    assert seen["ip"] == "127.0.0.1"


# ---- 3. ProxyFix only when configured ---------------------------------------


def test_configure_proxy_is_a_noop_at_zero_hops(app):
    app.config["TRUSTED_PROXY_HOPS"] = 0
    _configure_proxy(app)
    assert not isinstance(app.wsgi_app, ProxyFix)


def test_configure_proxy_installs_proxy_fix_at_one_hop(app):
    app.config["TRUSTED_PROXY_HOPS"] = 1
    _configure_proxy(app)
    assert isinstance(app.wsgi_app, ProxyFix)


def test_proxy_fix_rewrites_remote_addr_from_the_last_hop(app, make_user):
    app.config["TRUSTED_PROXY_HOPS"] = 1
    _configure_proxy(app)
    c, seen = _install_probe(app, make_user, "/_probe_remote_addr2")
    c.get(
        "/_probe_remote_addr2",
        headers={"X-Forwarded-For": "198.51.100.7, 203.0.113.9"},
    )
    # ProxyFix trusts exactly one hop, so it takes the rightmost value.
    assert seen["ip"] == "203.0.113.9"


def test_proxy_hops_default_is_off_in_every_config():
    from config import Config

    assert Config.TRUSTED_PROXY_HOPS == 0


# ---- 4. one database location for every environment -------------------------


def test_development_and_production_share_the_default_database():
    """They previously disagreed (instance/vms.db vs ./vms.db), so a
    production boot without DATABASE_URL opened a second, empty database."""
    assert DevConfig.SQLALCHEMY_DATABASE_URI == ProdConfig.SQLALCHEMY_DATABASE_URI
    assert ProdConfig.SQLALCHEMY_DATABASE_URI == DEFAULT_DB_URI
    assert ProdConfig.SQLALCHEMY_DATABASE_URI.endswith("/instance/vms.db")


def test_database_url_still_overrides_the_default(monkeypatch):
    """The env var is read at import time, so re-import to observe it."""
    import importlib

    import config as config_module

    monkeypatch.setenv("DATABASE_URL", "sqlite:////tmp/elsewhere.db")
    importlib.reload(config_module)
    try:
        assert config_module.DevConfig.SQLALCHEMY_DATABASE_URI == (
            "sqlite:////tmp/elsewhere.db"
        )
        assert config_module.ProdConfig.SQLALCHEMY_DATABASE_URI == (
            "sqlite:////tmp/elsewhere.db"
        )
    finally:
        importlib.reload(config_module)  # restore the un-patched module


def test_testing_config_is_untouched_by_the_default():
    assert TestConfig.SQLALCHEMY_DATABASE_URI == "sqlite:///:memory:"


def test_secure_cookie_flag_follows_env(monkeypatch):
    """SESSION_COOKIE_SECURE=0 keeps logins working on a plain-http
    deployment (e.g. a PythonAnywhere free plan); default stays ON."""
    import importlib

    import config as config_module

    monkeypatch.setenv("SESSION_COOKIE_SECURE", "0")
    importlib.reload(config_module)
    try:
        assert config_module.ProdConfig.SESSION_COOKIE_SECURE is False
    finally:
        # monkeypatch only restores the env at teardown, so undo it here or
        # the "restore" reload would just re-read the patched value.
        monkeypatch.delenv("SESSION_COOKIE_SECURE", raising=False)
        importlib.reload(config_module)
    assert config_module.ProdConfig.SESSION_COOKIE_SECURE is True


# ---- 5. response security headers ------------------------------------------


def _headers(response):
    return {k.lower(): v for k, v in response.headers}


def test_every_page_carries_the_security_headers(client):
    resp = client.get("/vehicles/")
    assert resp.status_code == 200
    h = _headers(resp)
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "same-origin"
    assert h["cross-origin-opener-policy"] == "same-origin"
    assert "geolocation=()" in h["permissions-policy"]


def test_security_headers_survive_error_pages(client):
    resp = client.get("/no-such-page-for-header-test")
    assert resp.status_code == 404
    assert _headers(resp)["x-content-type-options"] == "nosniff"


def test_csp_is_strict_with_no_unsafe_inline(client):
    """'unsafe-inline' would defeat the whole policy, so it must never appear.

    The templates hold no inline <script>/style=/handler attributes, so the
    strict policy is safe today and stays strict by default tomorrow.
    """
    csp = _headers(client.get("/vehicles/"))["content-security-policy"]
    assert "default-src 'none'" in csp
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "form-action 'self'" in csp
    for weakness in ("'unsafe-inline'", "'unsafe-eval'", "*", "data:"):
        assert weakness not in csp, (weakness, csp)


def test_hsts_is_sent_only_on_an_https_only_deployment(app, client):
    # testing config has SESSION_COOKIE_SECURE unset -> no HSTS.
    assert "strict-transport-security" not in _headers(client.get("/vehicles/"))

    app.config["SESSION_COOKIE_SECURE"] = True
    h = _headers(client.get("/vehicles/"))
    assert h["strict-transport-security"] == "max-age=31536000; includeSubDomains"


def test_static_assets_are_hardened_too(client):
    resp = client.get("/static/css/style.css")
    assert resp.status_code == 200
    h = _headers(resp)
    assert h["x-content-type-options"] == "nosniff"
    assert "content-security-policy" in h


def test_app_does_not_emit_its_own_server_header(client):
    """Werkzeug adds no Server header, so nothing leaks from the app itself.

    Note for operators: gunicorn re-adds `Server: gunicorn` *outside* the WSGI
    app, where no after_request hook can remove it. Strip it at the proxy
    (nginx: `server_tokens off;` plus `proxy_hide_header Server;`), or accept
    that the stack is advertised. That is a server setting, not an app one.
    """
    assert "Server" not in client.get("/vehicles/").headers
