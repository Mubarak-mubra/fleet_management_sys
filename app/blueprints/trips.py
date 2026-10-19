from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import driver_service, project_service, trip_service, vehicle_service

bp = Blueprint("trips", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    vehicle_id = request.args.get("vehicle_id", type=int) or None
    status = request.args.get("status") or None
    project_id = request.args.get("project_id", type=int) or None
    items, total, pages = trip_service.list_trips(
        vehicle_id=vehicle_id, status=status, project_id=project_id, page=page
    )
    return render_template(
        "trips/list.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        vehicle_id=vehicle_id,
        status=status,
        project_id=project_id,
        vehicles=vehicle_service.vehicle_options(),
        projects=project_service.project_options(),
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            trip = trip_service.create_trip(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("trips.create"))
        flash(f"Trip to {trip.destination} created", "success")
        return redirect(url_for("trips.list"))
    return render_template(
        "trips/form.html",
        form_data={},
        mode="create",
        vehicles=vehicle_service.vehicle_options(),
        drivers=driver_service.driver_options(),
        projects=project_service.project_options(),
    )


@bp.route("/<int:trip_id>/")
def detail(trip_id):
    try:
        trip = trip_service.get_trip(trip_id)
    except LookupError:
        abort(404)
    return render_template(
        "trips/detail.html",
        trip=trip,
        cost=trip_service.trip_cost(trip_id),
        mode="detail",
        form_data={},
    )


@bp.route("/<int:trip_id>/edit", methods=["GET", "POST"])
def edit(trip_id):
    try:
        trip = trip_service.get_trip(trip_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            trip = trip_service.update_trip(trip_id, request.form.to_dict())
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("trips.edit", trip_id=trip_id))
        flash("Trip updated", "success")
        return redirect(url_for("trips.detail", trip_id=trip_id))
    form_data = {
        "vehicle_id": trip.vehicle_id,
        "project_id": trip.project_id,
        "driver_id": trip.driver_id,
        "driver_name": trip.driver_name,
        "purpose": trip.purpose,
        "origin": trip.origin,
        "destination": trip.destination,
        "start_time": trip.start_time.strftime("%Y-%m-%dT%H:%M") if trip.start_time else "",
        "end_time": trip.end_time.strftime("%Y-%m-%dT%H:%M") if trip.end_time else "",
        "distance_km": trip.distance_km if trip.distance_km is not None else "",
        "odometer_start": trip.odometer_start if trip.odometer_start is not None else "",
        "odometer_end": trip.odometer_end if trip.odometer_end is not None else "",
        "status": trip.status,
        "notes": trip.notes or "",
    }
    return render_template(
        "trips/form.html",
        form_data=form_data,
        mode="edit",
        trip=trip,
        vehicles=vehicle_service.vehicle_options(),
        drivers=driver_service.driver_options(),
        projects=project_service.project_options(),
    )


@bp.route("/<int:trip_id>/start", methods=["POST"])
def start(trip_id):
    try:
        trip_service.start_trip(trip_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("trips.list"))
    flash("Trip started", "success")
    return redirect(url_for("trips.list"))


@bp.route("/<int:trip_id>/complete", methods=["POST"])
def complete(trip_id):
    try:
        trip_service.complete_trip(
            trip_id,
            end_time=request.form.get("end_time"),
            distance_km=request.form.get("distance_km"),
        )
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("trips.list"))
    flash("Trip completed", "success")
    return redirect(url_for("trips.list"))


@bp.route("/<int:trip_id>/cancel", methods=["POST"])
def cancel(trip_id):
    try:
        trip_service.cancel_trip(trip_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("trips.list"))
    flash("Trip cancelled", "success")
    return redirect(url_for("trips.list"))


@bp.route("/<int:trip_id>/delete", methods=["POST"])
def delete(trip_id):
    try:
        trip_service.delete_trip(trip_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("trips.list"))
    flash("Trip deleted", "success")
    return redirect(url_for("trips.list"))
