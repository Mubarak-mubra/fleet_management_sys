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
    """One CSV with every cost booked to the project, for Excel/Sheets."""
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
    writer.writerow(["Type", "Date", "Vehicle", "Details", "Liters", "Distance km", "Cost"])

    for log in report["fuel_logs"]:
        writer.writerow(
            [
                "fuel",
                log.fuel_date.isoformat(),
                log.vehicle.plate_number if log.vehicle else "",
                log.supplier or "",
                f"{log.liters:g}" if log.liters is not None else "",
                "",
                f"{log.computed_total:.2f}",
            ]
        )
    for log in report["maintenance_logs"]:
        writer.writerow(
            [
                "maintenance",
                log.performed_date.isoformat() if log.performed_date else "",
                log.vehicle.plate_number if log.vehicle else "",
                f"{log.maintenance_type}: {log.description}",
                "",
                "",
                f"{(log.cost or 0):.2f}",
            ]
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
        distance = (
            trip.distance_km
            or (
                trip.odometer_end - trip.odometer_start
                if trip.odometer_start is not None and trip.odometer_end is not None
                else 0.0
            )
        )
        writer.writerow(
            [
                "trip",
                trip.start_time.date().isoformat() if trip.start_time else "",
                trip.vehicle.plate_number if trip.vehicle else "",
                f"{trip.origin} -> {trip.destination} ({trip.driver_name})",
                "",
                f"{distance:g}",
                "",
            ]
        )

    writer.writerow([])
    writer.writerow(["", "", "", "Fuel total", "", "", f"{report['fuel_total']:.2f}"])
    writer.writerow(["", "", "", "Maintenance total", "", "", f"{report['maintenance_total']:.2f}"])
    writer.writerow(["", "", "", "Expenses total", "", "", f"{report['expense_total']:.2f}"])
    writer.writerow(["", "", "", "GRAND TOTAL", "", "", f"{report['total']:.2f}"])

    filename = f"project-{project.code}-costs.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
