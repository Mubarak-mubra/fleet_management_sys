from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import vehicle_type_service

bp = Blueprint("vehicle_types", __name__)


@bp.route("/")
def list():
    """Manage the fleet's type registry — the list the vehicle form's Type
    dropdown is built from."""
    return render_template(
        "vehicle_types/list.html",
        types=vehicle_type_service.list_types(),
        mode="list",
    )


@bp.route("/new", methods=["POST"])
def create():
    try:
        vehicle_type = vehicle_type_service.create_type(request.form.to_dict())
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("vehicle_types.list"))
    flash(f"Vehicle type {vehicle_type.name} added", "success")
    return redirect(url_for("vehicle_types.list"))


@bp.route("/<int:type_id>/delete", methods=["POST"])
def delete(type_id):
    try:
        vehicle_type_service.delete_type(type_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("vehicle_types.list"))
    flash("Vehicle type deleted", "success")
    return redirect(url_for("vehicle_types.list"))
