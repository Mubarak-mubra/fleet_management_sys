from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import fuel_service, project_service, vehicle_service

bp = Blueprint("fuel", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    vehicle_id = request.args.get("vehicle_id", type=int) or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    try:
        items, total, pages = fuel_service.list_fuel_logs(
            vehicle_id=vehicle_id, date_from=date_from, date_to=date_to, page=page
        )
    except ValueError as exc:
        flash(str(exc), "error")
        items, total, pages, page = [], 0, 1, 1
    return render_template(
        "fuel/list.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        vehicle_id=vehicle_id,
        date_from=date_from,
        date_to=date_to,
        vehicles=vehicle_service.vehicle_options(),
        efficiency=fuel_service.fuel_efficiency(vehicle_id),
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            log = fuel_service.create_fuel_log(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("fuel.create"))
        flash(f"Fuel log of {log.liters} L created", "success")
        return redirect(url_for("fuel.list"))
    return render_template(
        "fuel/form.html",
        form_data={},
        mode="create",
        vehicles=vehicle_service.vehicle_options(),
        projects=project_service.project_options(),
    )


@bp.route("/<int:log_id>/edit", methods=["GET", "POST"])
def edit(log_id):
    try:
        log = fuel_service.get_fuel_log(log_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            log = fuel_service.update_fuel_log(log_id, request.form.to_dict())
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("fuel.edit", log_id=log_id))
        flash("Fuel log updated", "success")
        return redirect(url_for("fuel.list"))
    form_data = {
        "vehicle_id": log.vehicle_id,
        "project_id": log.project_id,
        "fuel_date": log.fuel_date.isoformat() if log.fuel_date else "",
        "liters": log.liters,
        "cost_per_liter": log.cost_per_liter if log.cost_per_liter is not None else "",
        "total_cost": log.total_cost if log.total_cost is not None else "",
        "supplier": log.supplier or "",
        "odometer": log.odometer if log.odometer is not None else "",
        "receipt_ref": log.receipt_ref or "",
        "notes": log.notes or "",
    }
    return render_template(
        "fuel/form.html",
        form_data=form_data,
        mode="edit",
        log=log,
        vehicles=vehicle_service.vehicle_options(),
        projects=project_service.project_options(),
    )


@bp.route("/<int:log_id>/delete", methods=["POST"])
def delete(log_id):
    try:
        fuel_service.delete_fuel_log(log_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("fuel.list"))
    flash("Fuel log deleted", "success")
    return redirect(url_for("fuel.list"))
