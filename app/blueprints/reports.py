import csv
import io
from datetime import date, timedelta

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

from app.services import report_service

bp = Blueprint("reports", __name__)


def _shift_month(year: int, month: int, delta: int) -> str:
    """First day of the previous/next month, as a YYYY-MM query value."""
    if delta < 0:
        first = date(year, month, 1) - timedelta(days=1)
    else:
        # Step to the 12th to stay clear of month-length quirks, then forward.
        first = date(year, month, 12) + timedelta(days=31)
        first = date(first.year, first.month, 1)
    return f"{first.year}-{first.month:02d}"


@bp.route("/")
def index():
    return redirect(url_for("reports.monthly"))


@bp.route("/monthly/")
def monthly():
    month = request.args.get("month") or None
    try:
        data = report_service.monthly_summary(month)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.monthly"))
    prev_month = _shift_month(data["year"], data["month"], -1)
    next_month = _shift_month(data["year"], data["month"], 1)
    return render_template(
        "reports/monthly.html",
        data=data,
        month=f"{data['year']}-{data['month']:02d}",
        prev_month=prev_month,
        next_month=next_month,
    )


@bp.route("/monthly/csv")
def monthly_csv():
    """The month's fleet costs per vehicle and per category, for Excel/Sheets."""
    month = request.args.get("month") or None
    try:
        data = report_service.monthly_summary(month)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("reports.monthly"))

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([f"Fleet summary — {data['label']}"])
    writer.writerow([])
    writer.writerow(["By vehicle"])
    writer.writerow(
        ["Vehicle", "Plate", "Fuel count", "Liters", "Fuel cost", "Maint. count", "Maint. cost", "Expense count", "Expense cost", "Total"]
    )
    for entry in data["vehicles"]:
        veh = entry["vehicle"]
        writer.writerow(
            [
                veh.name,
                veh.plate_number,
                entry["fuel"]["count"],
                f"{entry['fuel']['liters']:g}",
                f"{entry['fuel']['cost']:.2f}",
                entry["maintenance"]["count"],
                f"{entry['maintenance']['cost']:.2f}",
                entry["expenses"]["count"],
                f"{entry['expenses']['cost']:.2f}",
                f"{entry['total']:.2f}",
            ]
        )
    if data["unassigned_total"]:
        writer.writerow(["(no vehicle / fleet-wide)", "", "", "", "", "", "", "", "", f"{data['unassigned_total']:.2f}"])

    writer.writerow([])
    writer.writerow(["By expense category"])
    writer.writerow(["Category", "Amount"])
    for category, total in sorted(data["expense_by_category"].items()):
        writer.writerow([category, f"{total:.2f}"])

    writer.writerow([])
    writer.writerow(["Fuel total", f"{data['fuel_total']:.2f}"])
    writer.writerow(["Maintenance total", f"{data['maintenance_total']:.2f}"])
    writer.writerow(["Expenses total", f"{data['expense_total']:.2f}"])
    writer.writerow(["Trips started", data["trip_count"]])
    writer.writerow(["GRAND TOTAL", f"{data['grand_total']:.2f}"])

    filename = f"fleet-summary-{data['year']}-{data['month']:02d}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
