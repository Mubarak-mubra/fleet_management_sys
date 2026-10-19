"""Authentication wiring: session handling, route guards, CSRF.

Route protection is applied globally in ``before_request`` rather than by
decorating each view, so a newly added endpoint is protected by default. The
only escape hatch is the explicit allow-list below — forgetting to protect a
route is impossible; forgetting to *expose* one is a deliberate act.

CSRF is handled by ``flask_wtf.csrf.CSRFProtect``, which registers its own
``before_request`` hook and validates every state-changing request. It is
initialised here alongside the auth guards so both live in one place.
"""
from functools import wraps

from flask import abort, current_app, g, redirect, request, url_for
from flask_login import LoginManager, UserMixin, current_user
from flask_wtf.csrf import CSRFProtect

from app.models import User

login_manager = LoginManager()
csrf = CSRFProtect()

# Endpoints reachable without a session. `static` is assets only; `auth.login`
# must be reachable or nobody could ever sign in. Everything else requires a
# logged-in user.
PUBLIC_ENDPOINTS = frozenset({"static", "auth.login"})

# Blueprints whose endpoints are admin-only (account management).
ADMIN_BLUEPRINTS = frozenset({"users"})

# Methods that mutate state and therefore require a CSRF token.
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# --- response hardening -----------------------------------------------------
# Applied to every reply, including the 404/500 pages and static assets.
#
# The CSP is deliberately strict because the templates contain no inline
# <script>, no inline style="", no event-handler attributes and no external
# hosts — everything the page needs is served from /static. `default-src 'none'`
# then means "anything we forgot to list stays blocked", so a future template
# cannot quietly introduce an inline script. Adding one requires either a hash
# or a nonce, which is the friction working as designed.
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",                    # no framing: clickjacking
    "Referrer-Policy": "same-origin",             # never leak internal URLs
    "X-Permitted-Cross-Domain-Policies": "none",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Permissions-Policy": (
        "geolocation=(), camera=(), microphone=(), payment=(), usb=()"
    ),
    "Content-Security-Policy": (
        "default-src 'none'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self'; "
        "font-src 'self'; "
        "connect-src 'self'; "
        "manifest-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}

# HSTS is only sent where the deployment is already HTTPS-only (production sets
# SESSION_COOKIE_SECURE). It cannot be un-sent, so it is never emitted on plain
# http where a dev is serving locally over http.
HSTS_HEADER = "Strict-Transport-Security"
HSTS_VALUE = "max-age=31536000; includeSubDomains"


class _CurrentUser(UserMixin):
    """Adapts the User model to Flask-Login's interface.

    Kept out of ``app.models`` so models stay importable without Flask-Login
    and context-free, matching the project's model convention.
    """

    def __init__(self, user: User):
        self._user = user

    @property
    def id(self) -> str:
        return str(self._user.id)

    @property
    def role(self) -> str:
        return self._user.role or ""

    @property
    def is_admin(self) -> bool:
        return self._user.is_admin

    @property
    def can_write(self) -> bool:
        return self._user.can_write

    @property
    def username(self) -> str:
        return self._user.username

    @property
    def display_name(self) -> str:
        return self._user.display_name or self._user.username

    @property
    def is_active(self) -> bool:
        return bool(self._user.active)

    # Passthroughs so views never reach into `._user`.
    @property
    def model(self) -> User:
        return self._user

    @property
    def id_int(self) -> int:
        return self._user.id

    def check_password(self, password: str) -> bool:
        return self._user.check_password(password)


def init_security(app):
    app.config.setdefault("WTF_CSRF_ENABLED", True)

    login_manager.init_app(app)

    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"
    # Regenerates the session key on login to defeat session fixation.
    login_manager.session_protection = "strong"

    @login_manager.user_loader
    def _load(user_id):
        try:
            user = db_get_user(int(user_id))
        except (TypeError, ValueError):
            return None
        if user is None or not user.active:
            return None
        return _CurrentUser(user)

    @login_manager.unauthorized_handler
    def _unauthorized():
        if request.path.startswith("/api/"):
            abort(401)
        target = request.full_path.rstrip("?") if request.query_string else request.path
        return redirect(url_for("auth.login", next=target))

    _register_request_guards(app)
    _register_security_headers(app)

    # Registered LAST on purpose: Flask runs before_request hooks in
    # registration order, and hooks return early when one produces a response.
    # Auth first means an anonymous or expired-session POST is sent to the
    # login page (302) instead of a bare 400. CSRF still runs for every
    # request that clears auth — which is every request capable of mutating
    # anything, since auth rejects the rest before they reach a view.
    csrf.init_app(app)


def db_get_user(user_id: int) -> User | None:
    return User.query.get(user_id)


def _register_request_guards(app):
    @app.before_request
    def _enforce_auth():
        # Escape hatch for tests only; never set it in a real deployment.
        if app.config.get("LOGIN_DISABLED"):
            g.user = None
            return

        endpoint = request.endpoint or ""

        if endpoint in PUBLIC_ENDPOINTS:
            g.user = current_user if current_user.is_authenticated else None
            return

        # Not signed in -> redirect to login (HTML) or 401 (API paths).
        if not current_user.is_authenticated:
            return login_manager.unauthorized()

        g.user = current_user

        # Admin-only blueprints, checked before anything else specific.
        blueprint = endpoint.split(".", 1)[0]
        if blueprint in ADMIN_BLUEPRINTS and not current_user.is_admin:
            abort(403)

        # Viewers may read but never mutate, regardless of endpoint.
        if request.method in UNSAFE_METHODS and not current_user.can_write:
            abort(403)

    @app.context_processor
    def _inject_user():
        return {"current_user": current_user, "g": g}


def _register_security_headers(app):
    @app.after_request
    def _set_security_headers(response):
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)

        if app.config.get("SESSION_COOKIE_SECURE"):
            response.headers.setdefault(HSTS_HEADER, HSTS_VALUE)

        # Belt and braces: the app itself never sets a Server header (Werkzeug
        # adds none), but this guarantees it can't creep in from a middleware.
        # gunicorn still adds `Server: gunicorn` outside the WSGI app — that
        # has to be hidden at the proxy, not here.
        response.headers.pop("Server", None)
        return response


def role_required(*roles):
    """Per-view role guard. The global guards already cover whole blueprints;
    use this only where one view inside a shared blueprint needs a tighter rule."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


__all__ = [
    "init_security",
    "login_manager",
    "csrf",
    "role_required",
    "SECURITY_HEADERS",
    "HSTS_HEADER",
    "PUBLIC_ENDPOINTS",
    "ADMIN_BLUEPRINTS",
    "UNSAFE_METHODS",
]
