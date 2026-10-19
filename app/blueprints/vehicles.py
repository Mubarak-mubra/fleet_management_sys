from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import fuel_service, vehicle_service

bp = Blueprint("vehicles", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    status = request.args.get("status") or None
    q = request.args.get("q") or None
    items, total, pages = vehicle_service.list_vehicles(status=status, q=q, page=page)
    return render_template(
        "vehicles/list.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        status=status,
        q=q,
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            vehicle = vehicle_service.create_vehicle(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("vehicles.create"))
        flash(f"Vehicle {vehicle.name} created", "success")
        return redirect(url_for("vehicles.list"))
    return render_template("vehicles/form.html", form_data={}, mode="create")


@bp.route("/<int:vehicle_id>/")
def detail(vehicle_id):
    try:
        vehicle = vehicle_service.get_vehicle(vehicle_id)
    except LookupError:
        abort(404)
    summary = vehicle_service.vehicle_summary(vehicle_id)
    return render_template(
        "vehicles/detail.html",
        vehicle=vehicle,
        summary=summary,
        efficiency=fuel_service.fuel_efficiency(vehicle_id),
        mode="detail",
        form_data={},
    )


@bp.route("/<int:vehicle_id>/edit", methods=["GET", "POST"])
def edit(vehicle_id):
    try:
        vehicle = vehicle_service.get_vehicle(vehicle_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            vehicle = vehicle_service.update_vehicle(vehicle_id, request.form.to_dict())
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("vehicles.edit", vehicle_id=vehicle_id))
        flash(f"Vehicle {vehicle.name} updated", "success")
        return redirect(url_for("vehicles.detail", vehicle_id=vehicle_id))
    form_data = {
        "name": vehicle.name,
        "plate_number": vehicle.plate_number,
        "vehicle_type": vehicle.vehicle_type,
        "make": vehicle.make or "",
        "model": vehicle.model or "",
        "year": vehicle.year or "",
        "status": vehicle.status,
        "odometer": vehicle.odometer,
        "fuel_capacity_liters": vehicle.fuel_capacity_liters or "",
        "notes": vehicle.notes or "",
    }
    return render_template(
        "vehicles/form.html", form_data=form_data, mode="edit", vehicle=vehicle
    )


@bp.route("/<int:vehicle_id>/delete", methods=["POST"])
def delete(vehicle_id):
    try:
        vehicle_service.delete_vehicle(vehicle_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("vehicles.list"))
    flash("Vehicle deleted", "success")
    return redirect(url_for("vehicles.list"))
