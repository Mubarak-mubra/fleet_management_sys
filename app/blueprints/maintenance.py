from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import maintenance_service, vehicle_service

bp = Blueprint("maintenance", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    vehicle_id = request.args.get("vehicle_id", type=int) or None
    status = request.args.get("status") or None
    items, total, pages = maintenance_service.list_maintenance(
        vehicle_id=vehicle_id, status=status, page=page
    )
    return render_template(
        "maintenance/list.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        vehicle_id=vehicle_id,
        status=status,
        vehicles=vehicle_service.vehicle_options(),
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            log = maintenance_service.create_maintenance(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("maintenance.create"))
        flash(f"Maintenance '{log.description}' created", "success")
        return redirect(url_for("maintenance.list"))
    return render_template(
        "maintenance/form.html",
        form_data={},
        mode="create",
        vehicles=vehicle_service.vehicle_options(),
    )


@bp.route("/<int:maintenance_id>/")
def detail(maintenance_id):
    try:
        log = maintenance_service.get_maintenance(maintenance_id)
    except LookupError:
        abort(404)
    return render_template(
        "maintenance/detail.html", maintenance=log, mode="detail", form_data={}
    )


@bp.route("/<int:maintenance_id>/edit", methods=["GET", "POST"])
def edit(maintenance_id):
    try:
        log = maintenance_service.get_maintenance(maintenance_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            log = maintenance_service.update_maintenance(
                maintenance_id, request.form.to_dict()
            )
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("maintenance.edit", maintenance_id=maintenance_id))
        flash("Maintenance record updated", "success")
        return redirect(url_for("maintenance.detail", maintenance_id=maintenance_id))
    form_data = {
        "vehicle_id": log.vehicle_id,
        "maintenance_type": log.maintenance_type,
        "description": log.description,
        "performed_date": log.performed_date.isoformat() if log.performed_date else "",
        "next_due_date": log.next_due_date.isoformat() if log.next_due_date else "",
        "cost": log.cost,
        "odometer": log.odometer if log.odometer is not None else "",
        "vendor": log.vendor or "",
        "status": log.status,
        "notes": log.notes or "",
    }
    return render_template(
        "maintenance/form.html",
        form_data=form_data,
        mode="edit",
        maintenance=log,
        vehicles=vehicle_service.vehicle_options(),
    )


@bp.route("/<int:maintenance_id>/delete", methods=["POST"])
def delete(maintenance_id):
    try:
        maintenance_service.delete_maintenance(maintenance_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("maintenance.list"))
    flash("Maintenance record deleted", "success")
    return redirect(url_for("maintenance.list"))
