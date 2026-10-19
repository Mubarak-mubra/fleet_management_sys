from datetime import date

from flask import Blueprint, render_template

from app.models import Vehicle
from app.services import fuel_service, maintenance_service, trip_service

bp = Blueprint("dashboard", __name__)


@bp.route("/", methods=["GET"])
def index():
    """Fleet snapshot: four counts up top, then the detail tables below.

    The KPI row reports operational state only (how many vehicles, how many
    usable, how many in the shop, how many out today). Money deliberately
    lives on its own pages — the fuel, maintenance and expense lists each
    total their own figures — so the dashboard never double-counts a cost
    that two screens would report differently.
    """
    recent_trips = trip_service.list_trips()[0][:5]
    recent_fuel = fuel_service.list_fuel_logs()[0][:5]
    context = {
        "page_title": "Dashboard",
        "vehicle_count": Vehicle.query.count(),
        "available_count": Vehicle.query.filter(Vehicle.status == "active").count(),
        "maintenance_count": Vehicle.query.filter(
            Vehicle.status == "maintenance"
        ).count(),
        "today_trip_count": trip_service.trips_active_on(),
        "today": date.today(),
        "overdue": maintenance_service.overdue_items(),
        "recent_trips": recent_trips,
        "recent_fuel": recent_fuel,
    }
    return render_template("index.html", **context)
