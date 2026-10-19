"""Monthly fleet cost summary — one chosen month, whole fleet.

Pure data assembly for the Reports page: totals per vehicle, per record
type and per expense category, all restricted to one calendar month.
Everything is date-filtered against the month window so the page, its CSV
and the per-vehicle breakdown can never disagree.
"""
from datetime import date, datetime, time, timedelta

from sqlalchemy import func

from extensions import db
from app.models import Expense, FuelLog, MaintenanceLog, TripLog, Vehicle

from .parsing import parse_date


def _month_window(year: int, month: int) -> tuple[date, date, date]:
    """First day, last day, and first day of the following month."""
    start = date(year, month, 1)
    if month == 12:
        next_start = date(year + 1, 1, 1)
    else:
        next_start = date(year, month + 1, 1)
    end = next_start - timedelta(days=1)
    return start, end, next_start


def _parse_month(month: str | date | None) -> tuple[int, int]:
    """Accept 'YYYY-MM' (or a date); default to the current month."""
    raw = str(month or "").strip()
    if not raw:
        today = date.today()
        return today.year, today.month
    try:
        year_str, month_str = raw.split("-", 1)
        year, mon = int(year_str), int(month_str)
        date(year, mon, 1)  # validates range
        return year, mon
    except ValueError:
        raise ValueError("Month must look like 2026-10") from None


def monthly_summary(month: str | None = None) -> dict:
    year, mon = _parse_month(month)
    start, end, next_start = _month_window(year, mon)

    fuel_rows = (
        db.session.query(
            FuelLog.vehicle_id,
            func.count(FuelLog.id),
            func.coalesce(func.sum(FuelLog.liters), 0.0),
            func.coalesce(
                func.sum(db.case((FuelLog.total_cost.isnot(None), FuelLog.total_cost), else_=None)),
                0.0,
            ),
        )
        .filter(FuelLog.fuel_date >= start, FuelLog.fuel_date <= end)
        .group_by(FuelLog.vehicle_id)
        .all()
    )
    # total_cost may be NULL on older rows where liters x cost_per_liter was
    # never materialised; compute those per-row rather than losing them.
    fuel_by_vehicle: dict[int, dict] = {}
    for veh_id, count, liters, total in fuel_rows:
        fuel_by_vehicle[veh_id] = {"count": count, "liters": float(liters), "cost": float(total)}
    unpriced = (
        FuelLog.query.filter(
            FuelLog.fuel_date >= start,
            FuelLog.fuel_date <= end,
            FuelLog.total_cost.is_(None),
        ).all()
    )
    for log in unpriced:
        entry = fuel_by_vehicle.setdefault(
            log.vehicle_id, {"count": 0, "liters": 0.0, "cost": 0.0}
        )
        entry["cost"] += log.computed_total

    maint_rows = (
        db.session.query(
            MaintenanceLog.vehicle_id,
            func.count(MaintenanceLog.id),
            func.coalesce(func.sum(MaintenanceLog.cost), 0.0),
        )
        .filter(
            MaintenanceLog.performed_date >= start,
            MaintenanceLog.performed_date <= end,
        )
        .group_by(MaintenanceLog.vehicle_id)
        .all()
    )
    maint_by_vehicle = {vid: {"count": cnt, "cost": float(cost)} for vid, cnt, cost in maint_rows}

    expense_rows = (
        db.session.query(
            Expense.vehicle_id,
            func.count(Expense.id),
            func.coalesce(func.sum(Expense.amount), 0.0),
        )
        .filter(Expense.expense_date >= start, Expense.expense_date <= end)
        .group_by(Expense.vehicle_id)
        .all()
    )
    expense_by_vehicle = {vid: {"count": cnt, "cost": float(cost)} for vid, cnt, cost in expense_rows}

    expense_by_category_rows = (
        db.session.query(Expense.category, func.coalesce(func.sum(Expense.amount), 0.0))
        .filter(Expense.expense_date >= start, Expense.expense_date <= end)
        .group_by(Expense.category)
        .all()
    )
    expense_by_category = {cat: float(total) for cat, total in expense_by_category_rows}

    trip_count = TripLog.query.filter(
        TripLog.start_time >= datetime.combine(start, time.min),
        TripLog.start_time < datetime.combine(next_start, time.min),
    ).count()

    # Per-vehicle rollup across all three cost types. Records with no vehicle
    # (fleet-wide expenses) keep their own "unassigned" bucket instead of
    # silently vanishing from the totals.
    vehicle_ids = (set(fuel_by_vehicle) | set(maint_by_vehicle) | set(expense_by_vehicle)) - {None}
    vehicles = {}
    if vehicle_ids:
        for veh in Vehicle.query.filter(Vehicle.id.in_(vehicle_ids)).all():
            fuel = fuel_by_vehicle.get(veh.id, {"count": 0, "liters": 0.0, "cost": 0.0})
            maint = maint_by_vehicle.get(veh.id, {"count": 0, "cost": 0.0})
            exp = expense_by_vehicle.get(veh.id, {"count": 0, "cost": 0.0})
            vehicles[veh.id] = {
                "vehicle": veh,
                "fuel": fuel,
                "maintenance": maint,
                "expenses": exp,
                "total": fuel["cost"] + maint["cost"] + exp["cost"],
            }

    fuel_total = sum(entry["cost"] for entry in fuel_by_vehicle.values())
    maintenance_total = sum(entry["cost"] for entry in maint_by_vehicle.values())
    expense_total = sum(entry["cost"] for entry in expense_by_vehicle.values())
    fuel_liters = sum(entry["liters"] for entry in fuel_by_vehicle.values())
    unassigned_total = (
        fuel_by_vehicle.get(None, {"cost": 0.0})["cost"]
        + maint_by_vehicle.get(None, {"cost": 0.0})["cost"]
        + expense_by_vehicle.get(None, {"cost": 0.0})["cost"]
    )

    return {
        "year": year,
        "month": mon,
        "start": start,
        "end": end,
        "label": f"{start.strftime('%B %Y')}",
        "vehicles": sorted(vehicles.values(), key=lambda e: -e["total"]),
        "expense_by_category": expense_by_category,
        "trip_count": trip_count,
        "fuel_total": fuel_total,
        "maintenance_total": maintenance_total,
        "expense_total": expense_total,
        "unassigned_total": unassigned_total,
        "grand_total": fuel_total + maintenance_total + expense_total,
        "fuel_liters": fuel_liters,
    }
