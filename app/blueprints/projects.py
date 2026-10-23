import csv
import io

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from app.services import project_service

bp = Blueprint("projects", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    status = request.args.get("status") or None
    q = request.args.get("q") or None
    try:
        items, total, pages = project_service.list_projects(
            status=status, q=q, page=page
        )
    except ValueError as exc:
        flash(str(exc), "error")
        items, total, pages = [], 0, 1
    return render_template(
        "projects/list.html",
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
            project = project_service.create_project(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("projects.create"))
        flash(f"Project {project.code} created", "success")
        return redirect(url_for("projects.detail", project_id=project.id))
    return render_template("projects/form.html", form_data={}, mode="create")


@bp.route("/<int:project_id>/")
def detail(project_id):
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    try:
        report = project_service.project_cost_report(
            project_id, date_from=date_from, date_to=date_to
        )
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("projects.detail", project_id=project_id))
    return render_template(
        "projects/detail.html",
        report=report,
        project=report["project"],
        date_from=date_from,
        date_to=date_to,
    )


@bp.route("/<int:project_id>/edit", methods=["GET", "POST"])
def edit(project_id):
    try:
        project = project_service.get_project(project_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            project = project_service.update_project(project_id, request.form.to_dict())
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("projects.edit", project_id=project_id))
        flash("Project updated", "success")
        return redirect(url_for("projects.detail", project_id=project.id))
    form_data = {
        "name": project.name,
        "code": project.code,
        "client": project.client or "",
        "location": project.location or "",
        "start_date": project.start_date.isoformat() if project.start_date else "",
        "end_date": project.end_date.isoformat() if project.end_date else "",
        "status": project.status,
        "notes": project.notes or "",
    }
    return render_template(
        "projects/form.html", form_data=form_data, mode="edit", project=project
    )


@bp.route("/<int:project_id>/delete", methods=["POST"])
def delete(project_id):
    try:
        project_service.delete_project(project_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("projects.detail", project_id=project_id))
    flash("Project deleted", "success")
    return redirect(url_for("projects.list"))


@bp.route("/<int:project_id>/csv")
def download_csv(project_id):
    """One CSV with every cost for this project, for Excel/Sheets.

    Fuel and maintenance rows are per-vehicle estimates derived from trips
    (see project_service.project_cost_report), and are labelled as such —
    the trips, distance and litres behind them are real, only the split is
    arithmetic.
    """
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    try:
        report = project_service.project_cost_report(
            project_id, date_from=date_from, date_to=date_to
        )
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("projects.detail", project_id=project_id))

    project = report["project"]
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([f"Project {project.code} — {project.name}"])
    writer.writerow(["Filters", f"from {date_from or 'start'}", f"to {date_to or 'today'}"])
    writer.writerow([])
    writer.writerow(
        ["Type", "Date", "Vehicle", "Details", "Liters", "Distance km", "Cost (est.)"]
    )

    # Fuel and maintenance are not booked to a project anywhere (see their
    # models) — these rows are derived from trips x each vehicle's measured
    # efficiency, so they are estimates and say so in the Type column.
    for row in report["vehicle_rows"]:
        plate = row["vehicle"].plate_number if row["vehicle"] else ""
        eff = (
            f"{row['km_per_liter']:g} km/L"
            if row["km_per_liter"]
            else "fleet-average km/L (no measured figure)"
        )
        writer.writerow(
            [
                "fuel (estimate)",
                "",
                plate,
                f"{row['km']:g} km here at {eff}",
                f"{row['liters']:g}",
                "",
                f"{row['fuel_cost']:.2f}",
            ]
        )
        basis = row.get("maintenance_basis")
        detail = "share of vehicle maintenance by km"
        if basis:
            detail += (
                f" ({basis['fraction'] * 100:g}% of {basis['total_cost']:.2f}"
                f" = {basis['project_km']:g} of {basis['fleet_km']:g} km)"
            )
        writer.writerow(
            ["maintenance (estimate)", "", plate, detail, "", "", f"{row['maintenance_cost']:.2f}"]
        )
    for row in report["expenses"]:
        writer.writerow(
            [
                "expense",
                row.expense_date.isoformat(),
                row.vehicle.plate_number if row.vehicle else "Fleet-wide",
                f"{row.category}: {row.description}",
                "",
                "",
                f"{(row.amount or 0):.2f}",
            ]
        )
    for trip in report["trips"]:
        writer.writerow(
            [
                "trip",
                trip.start_time.date().isoformat() if trip.start_time else "",
                trip.vehicle.plate_number if trip.vehicle else "",
                f"{trip.origin} -> {trip.destination} ({trip.driver_name})",
                "",
                f"{project_service.trip_distance(trip):g}",
                "",
            ]
        )

    writer.writerow([])
    writer.writerow(["", "", "", "Fuel total (estimate)", "", "", f"{report['fuel_total']:.2f}"])
    writer.writerow(
        ["", "", "", "Maintenance total (estimate)", "", "", f"{report['maintenance_total']:.2f}"]
    )
    writer.writerow(["", "", "", "Expenses total", "", "", f"{report['expense_total']:.2f}"])
    writer.writerow(["", "", "", "GRAND TOTAL", "", "", f"{report['total']:.2f}"])

    filename = f"project-{project.code}-costs.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
