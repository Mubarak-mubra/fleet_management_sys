"""Fuel log business logic."""
from datetime import date

from extensions import db
from app.models import FuelLog, Vehicle

from .pagination import paginate
from .parsing import parse_date, parse_float
from .project_service import resolve_project


def _resolve_vehicle(raw) -> Vehicle:
    try:
        vehicle_id = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("Vehicle not found") from None
    vehicle = db.session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise ValueError("Vehicle not found")
    return vehicle


def _apply_odometer(vehicle: Vehicle, odometer: float | None) -> None:
    if odometer is not None and odometer > (vehicle.odometer or 0.0):
        vehicle.odometer = odometer


def list_fuel_logs(
    vehicle_id: int | None = None,
    date_from: date | str | None = None,
    date_to: date | str | None = None,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list, int, int]:
    query = FuelLog.query
    if vehicle_id:
        query = query.filter(FuelLog.vehicle_id == vehicle_id)
    if date_from not in (None, ""):
        query = query.filter(FuelLog.fuel_date >= parse_date(date_from, "date_from"))
    if date_to not in (None, ""):
        query = query.filter(FuelLog.fuel_date <= parse_date(date_to, "date_to"))
    query = query.order_by(FuelLog.fuel_date.desc())
    return paginate(query, page, per_page)


def get_fuel_log(log_id: int) -> FuelLog:
    log = db.session.get(FuelLog, log_id)
    if log is None:
        raise LookupError(f"Fuel log {log_id} not found")
    return log


def create_fuel_log(data: dict) -> FuelLog:
    try:
        vehicle = _resolve_vehicle(data.get("vehicle_id"))

        fuel_date = parse_date(data.get("fuel_date"), "fuel_date")
        if fuel_date is None:
            raise ValueError("Fuel date is required")

        liters = parse_float(data.get("liters"), "liters")
        if liters is None:
            raise ValueError("Liters is required")
        if liters <= 0:
            raise ValueError("Liters must be greater than 0")

        cost_per_liter = parse_float(data.get("cost_per_liter"), "cost_per_liter")
        if cost_per_liter is not None and cost_per_liter < 0:
            raise ValueError("Cost per liter cannot be negative")

        if data.get("total_cost") in (None, ""):
            total_cost = liters * (cost_per_liter or 0)
        else:
            total_cost = parse_float(data.get("total_cost"), "total_cost")

        log = FuelLog(
            vehicle_id=vehicle.id,
            project=resolve_project(data.get("project_id")),
            fuel_date=fuel_date,
            liters=liters,
            cost_per_liter=cost_per_liter,
            total_cost=total_cost,
            supplier=str(data.get("supplier") or "").strip() or None,
            receipt_ref=str(data.get("receipt_ref") or "").strip() or None,
            notes=data.get("notes") or None,
        )
        odometer = parse_float(data.get("odometer"), "odometer")
        if odometer is not None:
            log.odometer = odometer
            _apply_odometer(vehicle, odometer)

        db.session.add(log)
        db.session.commit()
        return log
    except Exception:
        db.session.rollback()
        raise


def update_fuel_log(log_id: int, data: dict) -> FuelLog:
    try:
        log = get_fuel_log(log_id)
        vehicle = db.session.get(Vehicle, log.vehicle_id)

        if "vehicle_id" in data:
            vehicle = _resolve_vehicle(data.get("vehicle_id"))
            log.vehicle_id = vehicle.id
        if "project_id" in data:
            log.project = resolve_project(data.get("project_id"))
        if "fuel_date" in data:
            fuel_date = parse_date(data.get("fuel_date"), "fuel_date")
            if fuel_date is None:
                raise ValueError("Fuel date is required")
            log.fuel_date = fuel_date
        if "liters" in data:
            liters = parse_float(data.get("liters"), "liters")
            if liters is None:
                raise ValueError("Liters is required")
            if liters <= 0:
                raise ValueError("Liters must be greater than 0")
            log.liters = liters
        if "cost_per_liter" in data:
            cost_per_liter = parse_float(data.get("cost_per_liter"), "cost_per_liter")
            if cost_per_liter is not None and cost_per_liter < 0:
                raise ValueError("Cost per liter cannot be negative")
            log.cost_per_liter = cost_per_liter
        if "total_cost" in data and data.get("total_cost") not in (None, ""):
            log.total_cost = parse_float(data.get("total_cost"), "total_cost")
        elif data.get("total_cost") in (None, ""):
            log.total_cost = log.liters * (log.cost_per_liter or 0)
        if "supplier" in data:
            log.supplier = str(data.get("supplier") or "").strip() or None
        if "receipt_ref" in data:
            log.receipt_ref = str(data.get("receipt_ref") or "").strip() or None
        if "notes" in data:
            log.notes = data.get("notes") or None
        if "odometer" in data:
            odometer = parse_float(data.get("odometer"), "odometer")
            if odometer is not None:
                log.odometer = odometer
                _apply_odometer(vehicle, odometer)

        db.session.commit()
        return log
    except Exception:
        db.session.rollback()
        raise


def delete_fuel_log(log_id: int) -> None:
    try:
        log = get_fuel_log(log_id)
        db.session.delete(log)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def fuel_efficiency(vehicle_id: int | None = None) -> dict:
    """Fuel efficiency in km/L using the fill-to-fill (tank) method.

    Between two consecutive fill-ups on the same vehicle the distance driven is
    ``odometer[2] - odometer[1]`` and the fuel burned is the liters added at
    the second fill — both tanks were full at each end of the interval, so
    that fill is exactly what the distance consumed.

    A pair is skipped when either odometer is missing or the reading went
    backwards (odometer replaced/reset, or a typo), since neither produces a
    trustworthy distance. Efficiency is reported as a weighted average
    (total km / total liters) rather than a mean of ratios: one 2,000 km
    interval should outweigh one 20 km interval.
    """
    query = FuelLog.query
    if vehicle_id:
        query = query.filter(FuelLog.vehicle_id == vehicle_id)

    grouped: dict[int, list[FuelLog]] = {}
    for log in query.order_by(FuelLog.fuel_date.asc(), FuelLog.id.asc()).all():
        grouped.setdefault(log.vehicle_id, []).append(log)

    by_vehicle: dict[int, dict] = {}
    intervals: list[dict] = []

    for veh_id, logs in grouped.items():
        # Odometer is the ruler here, so keep only readings that can be
        # compared: present, and carrying a fuel amount to charge the interval.
        readings = [
            (log.fuel_date, float(log.odometer), float(log.liters), log.id)
            for log in logs
            if log.odometer is not None and (log.liters or 0) > 0
        ]

        total_km = 0.0
        total_liters = 0.0
        for prev, curr in zip(readings, readings[1:]):
            distance = curr[1] - prev[1]
            if distance <= 0:
                continue  # odometer did not advance: reset or entry error
            liters = curr[2]
            total_km += distance
            total_liters += liters
            intervals.append(
                {
                    "fuel_log_id": curr[3],
                    "vehicle_id": veh_id,
                    "date": curr[0],
                    "km": distance,
                    "liters": liters,
                    "km_per_liter": distance / liters,
                }
            )

        if total_liters > 0:
            by_vehicle[veh_id] = {
                "km": total_km,
                "liters": total_liters,
                "km_per_liter": total_km / total_liters,
                "intervals": sum(1 for i in intervals if i["vehicle_id"] == veh_id),
            }

    total_km = sum(entry["km"] for entry in by_vehicle.values())
    total_liters = sum(entry["liters"] for entry in by_vehicle.values())
    return {
        "intervals": intervals,
        "by_vehicle": by_vehicle,
        "total_km": total_km,
        "total_liters": total_liters,
        "interval_count": len(intervals),
        "avg_km_per_liter": (total_km / total_liters) if total_liters else 0.0,
    }


def fuel_stats(vehicle_id: int | None = None) -> dict:
    query = FuelLog.query
    if vehicle_id:
        query = query.filter(FuelLog.vehicle_id == vehicle_id)
    logs = query.all()

    total_liters = sum(log.liters or 0 for log in logs)
    total_cost = sum(log.computed_total for log in logs)
    avg_cost_per_liter = (total_cost / total_liters) if total_liters else 0.0

    by_vehicle: dict[int, dict] = {}
    for log in logs:
        entry = by_vehicle.setdefault(log.vehicle_id, {"liters": 0.0, "cost": 0.0})
        entry["liters"] += log.liters or 0
        entry["cost"] += log.computed_total

    return {
        "total_liters": total_liters,
        "total_cost": total_cost,
        "avg_cost_per_liter": avg_cost_per_liter,
        "by_vehicle": by_vehicle,
    }
