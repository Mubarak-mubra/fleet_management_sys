from datetime import datetime, timezone

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.security import _CurrentUser
from app.services import auth_service

bp = Blueprint("auth", __name__)


def _safe_next(target: str | None) -> str | None:
    """Only honour redirects back to this host (blocks open-redirect abuse)."""
    if not target:
        return None
    from urllib.parse import urljoin, urlparse

    ref_url = urlparse(request.host_url)
    test = urlparse(urljoin(request.host_url, target))
    if test.scheme in ("http", "https") and ref_url.netloc == test.netloc:
        return target
    return None


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard.index"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        # `request.remote_addr` is the throttle key. It is only rewritten from
        # X-Forwarded-For when TRUSTED_PROXY_HOPS > 0 (see _configure_proxy),
        # so a forged header cannot be used to reset the counter per attempt.
        source = request.remote_addr
        try:
            user = auth_service.authenticate(username, password, source=source)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("auth/login.html", username=username, mode="login"), 401

        # `remember` is intentionally not offered: sessions are short-lived.
        login_user(_CurrentUser(user))
        # Mark the session permanent so PERMANENT_SESSION_LIFETIME (8h) is
        # actually enforced. Without this Flask issues a browser-session cookie
        # with no expiry at all, which lives until the browser closes — or
        # forever if it stays open.
        session.permanent = True
        flash(f"Welcome back, {user.display_name}.", "success")
        target = _safe_next(request.args.get("next")) or url_for("dashboard.index")
        return redirect(target)

    return render_template("auth/login.html", mode="login")


@bp.route("/logout", methods=["POST"])
def logout():
    logout_user()
    session.clear()
    flash("You have been signed out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")

        if not g.user.check_password(current):
            flash("Current password is incorrect.", "error")
            return render_template("auth/password.html", mode="password"), 400
        if new != confirm:
            flash("New passwords do not match.", "error")
            return render_template("auth/password.html", mode="password"), 400
        try:
            auth_service.update_user(
                g.user.id_int, {"password": new}, actor=g.user.model
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("auth/password.html", mode="password"), 400

        flash("Password updated.", "success")
        return redirect(url_for("dashboard.index"))

    return render_template("auth/password.html", mode="password")
