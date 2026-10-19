"""Admin-only account management.

The `users` blueprint is listed in `security.ADMIN_BLUEPRINTS`, so every
endpoint here requires an admin session before any view code runs. Nothing in
this file re-checks that deliberately — the global guard is the single source
of truth, and a view that duplicated it could drift out of sync.
"""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.services import auth_service

bp = Blueprint("users", __name__)


@bp.route("/")
def list():
    users = auth_service.list_users()
    return render_template(
        "users/list.html",
        users=users,
        total=len(users),
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            user = auth_service.create_user(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("users.create"))
        flash(f"Account '{user.username}' created.", "success")
        return redirect(url_for("users.list"))
    return render_template("users/form.html", form_data={}, mode="create", roles=auth_service.ROLES)


@bp.route("/<int:user_id>/edit", methods=["GET", "POST"])
def edit(user_id):
    try:
        user = auth_service.get_user(user_id)
    except LookupError:
        abort(404)

    if request.method == "POST":
        try:
            auth_service.update_user(user_id, request.form.to_dict(), actor=current_user.model)
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("users.edit", user_id=user_id))
        flash("Account updated.", "success")
        return redirect(url_for("users.list"))

    form_data = {
        "username": user.username,
        "display_name": user.display_name or "",
        "role": user.role,
        "active": "on" if user.active else "",
    }
    return render_template(
        "users/form.html",
        form_data=form_data,
        mode="edit",
        user=user,
        roles=auth_service.ROLES,
        setting_password=False,
    )


@bp.route("/<int:user_id>/password", methods=["POST"])
def reset_password(user_id):
    """Admin reset: sets a new password without knowing the old one."""
    try:
        user = auth_service.get_user(user_id)
    except LookupError:
        abort(404)
    try:
        auth_service.update_user(user_id, {"password": request.form.get("password", "")})
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("users.edit", user_id=user_id))
    flash(f"Password reset for '{user.username}'.", "success")
    return redirect(url_for("users.list"))


@bp.route("/<int:user_id>/delete", methods=["POST"])
def delete(user_id):
    try:
        auth_service.delete_user(user_id, actor=current_user.model)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("users.list"))
    flash("Account deleted.", "success")
    return redirect(url_for("users.list"))
