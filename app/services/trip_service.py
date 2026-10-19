"""Trip business logic."""
from datetime import date, datetime, time

from sqlalchemy import or_

from extensions import db
from app.models import TRIP_STATUSES, Driver, FuelLog, MaintenanceLog, TripLog, Vehicle
from app.models.base import utcnow

from .pagination import paginate
from .parsing import parse_datetime, parse_float
from .project_service import resolve_project

CREATE_STATUSES = ("planned", "in_progress")


def _required(data: dict, key: str, label: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    return value


def _resolve_vehicle(raw) -> Vehicle:
    try:
        vehicle_id = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError("Vehicle not found") from None
    vehicle = db.session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise ValueError("Vehicle not found")
    return vehicle


def list_trips(
    vehicle_id: int | None = None,
    status: str | None = None,
    project_id: int | None = None,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list, int, int]:
    query = TripLog.query
    if vehicle_id:
        query = query.filter(TripLog.vehicle_id == vehicle_id)
    if status:
        query = query.filter(TripLog.status == status)
    if project_id:
        query = query.filter(TripLog.project_id == project_id)
    query = query.order_by(TripLog.start_time.desc())
    return paginate(query, page, per_page)


def trips_active_on(day: date | None = None) -> int:
    """Count trips running on ``day`` — the dashboard's "today" figure.

    Counts a trip when it had already started by the end of that day and had
    not finished before it began, so a trip spanning midnight still counts on
    both days. Cancelled trips are excluded regardless of their timestamps:
    calling one off takes it off the board for every day, not just the day it
    was cancelled.

    An unfinished trip (no ``end_time``) counts as running from its start up
    to and including today, then drops off automatically once today moves past
    it — no background job required to expire stale trips.
    """
    day = day or date.today()
    day_start = datetime.combine(day, time.min)
    day_end = datetime.combine(day, time.max)
    return (
        TripLog.query.filter(
            TripLog.status != "cancelled",
            TripLog.start_time <= day_end,
            or_(TripLog.end_time.is_(None), TripLog.end_time >= day_start),
        )
        .count()
    )


def get_trip(trip_id: int) -> TripLog:
    trip = db.session.get(TripLog, trip_id)
    if trip is None:
        raise LookupError(f"Trip {trip_id} not found")
    return trip


def _resolve_driver(raw) -> Driver | None:
    """Resolve a submitted driver id; blank input means 'no driver selected'.

    Returns the Driver so the caller can snapshot its name onto the trip.
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        driver_id = int(raw)
    except ValueError:
        raise ValueError("Driver not found") from None
    driver = db.session.get(Driver, driver_id)
    if driver is None:
        raise ValueError("Driver not found")
    return driver


def _resolve_driver_field(data: dict) -> tuple[int | None, str]:
    """Return (driver_id, driver_name) for a submitted trip.

    A registered driver id is the source of truth and its name is snapshotted
    onto the trip, so history survives a later rename. A bare typed
    ``driver_name`` is still accepted (legacy/API callers) and links no driver.
    """
    driver = _resolve_driver(data.get("driver_id"))
    if driver is not None:
        return driver.id, driver.name
    return None, _required(data, "driver_name", "Driver name")


def create_trip(data: dict) -> TripLog:
    try:
        vehicle = _resolve_vehicle(data.get("vehicle_id"))
        driver_id, driver_name = _resolve_driver_field(data)
        purpose = _required(data, "purpose", "Purpose")
        origin = _required(data, "origin", "Origin")
        destination = _required(data, "destination", "Destination")

        start_time = parse_datetime(data.get("start_time"), "start_time")
        if start_time is None:
            raise ValueError("Start time is required")
        end_time = parse_datetime(data.get("end_time"), "end_time")
        if end_time is not None and end_time < start_time:
            raise ValueError("end_time must be after start_time")

        status = str(data.get("status") or "").strip()
        if status and status not in CREATE_STATUSES:
            raise ValueError("Invalid trip status")

        trip = TripLog(
            vehicle_id=vehicle.id,
            driver_id=driver_id,
            driver_name=driver_name,
            project=resolve_project(data.get("project_id")),
            purpose=purpose,
            origin=origin,
            destination=destination,
            start_time=start_time,
            end_time=end_time,
            status=status or "planned",
            notes=data.get("notes") or None,
        )
        distance_km = parse_float(data.get("distance_km"), "distance_km")
        if distance_km is not None:
            trip.distance_km = distance_km
        odometer_start = parse_float(data.get("odometer_start"), "odometer_start")
        if odometer_start is not None:
            trip.odometer_start = odometer_start
        odometer_end = parse_float(data.get("odometer_end"), "odometer_end")
        if odometer_end is not None:
            trip.odometer_end = odometer_end

        db.session.add(trip)
        db.session.commit()
        return trip
    except Exception:
        db.session.rollback()
        raise


def update_trip(trip_id: int, data: dict) -> TripLog:
    try:
        trip = get_trip(trip_id)

        if "vehicle_id" in data:
            trip.vehicle_id = _resolve_vehicle(data.get("vehicle_id")).id
        if "project_id" in data:
            trip.project = resolve_project(data.get("project_id"))
        if "driver_id" in data or "driver_name" in data:
            trip.driver_id, trip.driver_name = _resolve_driver_field(data)
        if "purpose" in data:
            trip.purpose = _required(data, "purpose", "Purpose")
        if "origin" in data:
            trip.origin = _required(data, "origin", "Origin")
        if "destination" in data:
            trip.destination = _required(data, "destination", "Destination")

        if "start_time" in data:
            start_time = parse_datetime(data.get("start_time"), "start_time")
            if start_time is None:
                raise ValueError("Start time is required")
            trip.start_time = start_time
        if "end_time" in data:
            end_time = parse_datetime(data.get("end_time"), "end_time")
            if end_time is not None and end_time < trip.start_time:
                raise ValueError("end_time must be after start_time")
            trip.end_time = end_time

        if "status" in data and str(data.get("status") or "").strip():
            status = str(data.get("status")).strip()
            if status not in TRIP_STATUSES:
                raise ValueError("Invalid trip status")
            trip.status = status

        if "distance_km" in data:
            distance_km = parse_float(data.get("distance_km"), "distance_km")
            if distance_km is not None:
                trip.distance_km = distance_km
        if "odometer_start" in data:
            odometer_start = parse_float(data.get("odometer_start"), "odometer_start")
            if odometer_start is not None:
                trip.odometer_start = odometer_start
        if "odometer_end" in data:
            odometer_end = parse_float(data.get("odometer_end"), "odometer_end")
            if odometer_end is not None:
                trip.odometer_end = odometer_end
        if "notes" in data:
            trip.notes = data.get("notes") or None

        db.session.commit()
        return trip
    except Exception:
        db.session.rollback()
        raise


def start_trip(trip_id: int) -> TripLog:
    try:
        trip = get_trip(trip_id)
        if trip.status != "planned":
            raise ValueError("Only planned trips can be started")
        if trip.start_time is None:
            trip.start_time = utcnow()
        trip.status = "in_progress"
        db.session.commit()
        return trip
    except Exception:
        db.session.rollback()
        raise


def complete_trip(
    trip_id: int,
    end_time: datetime | str | None = None,
    distance_km: float | str | None = None,
) -> TripLog:
    try:
        trip = get_trip(trip_id)
        if trip.status != "in_progress":
            raise ValueError("Only in-progress trips can be completed")

        if isinstance(end_time, str):
            end_time = parse_datetime(end_time, "end_time")
        if end_time is None:
            end_time = utcnow()
        if trip.start_time is not None and end_time < trip.start_time:
            raise ValueError("end_time must be after start_time")

        if isinstance(distance_km, str):
            distance_km = parse_float(distance_km, "distance_km")

        trip.end_time = end_time
        trip.status = "completed"

        if distance_km is not None and distance_km > 0:
            trip.distance_km = distance_km
            if trip.odometer_start is not None:
                trip.odometer_end = trip.odometer_start + distance_km
                vehicle = trip.vehicle
                vehicle.odometer = max(vehicle.odometer or 0.0, trip.odometer_end)

        db.session.commit()
        return trip
    except Exception:
        db.session.rollback()
        raise


def cancel_trip(trip_id: int) -> TripLog:
    try:
        trip = get_trip(trip_id)
        if trip.status not in ("planned", "in_progress"):
            raise ValueError("Only planned or in-progress trips can be cancelled")
        trip.status = "cancelled"
        db.session.commit()
        return trip
    except Exception:
        db.session.rollback()
        raise


def delete_trip(trip_id: int) -> None:
    try:
        trip = get_trip(trip_id)
        db.session.delete(trip)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def trip_cost(trip_id: int) -> dict:
    """Roll up what a trip actually cost, over the dates it spanned.

    Sums fuel and maintenance booked to the trip's vehicle while the trip was
    running, then divides by distance to give a per-kilometre figure. Both
    sources are date-filtered against the trip window, so a fill-up or service
    from a month earlier is never charged to this trip.

    Other ``Expense`` records are deliberately excluded: office rent or fleet
    insurance landing in the window is a period cost, not a cost caused by
    these kilometres. The dashboard reports those separately so nothing is
    double-counted either way.

    An unfinished trip (no ``end_time`` and not yet completed or cancelled) is
    priced up to today and flagged ``open`` — a running estimate, not a settled
    figure. A terminal trip whose end timestamp is missing is clamped to its
    start day instead, so a cancelled trip never sweeps up fill-ups booked
    weeks after it was called off.
    """
    trip = get_trip(trip_id)
    start = trip.start_time.date()
    terminal = trip.status in ("completed", "cancelled")

    if trip.end_time is not None:
        end = trip.end_time.date()
    elif terminal:
        end = start
    else:
        end = max(date.today(), start)

    open_trip = trip.end_time is None and not terminal
    if end < start:
        end = start

    vehicle_id = trip.vehicle_id
    fuel_cost = maintenance_cost = 0.0
    if vehicle_id is not None:
        fuel_cost = sum(
            log.computed_total
            for log in FuelLog.query.filter(
                FuelLog.vehicle_id == vehicle_id,
                FuelLog.fuel_date >= start,
                FuelLog.fuel_date <= end,
            )
        )
        maintenance_cost = sum(
            (m.cost or 0.0)
            for m in MaintenanceLog.query.filter(
                MaintenanceLog.vehicle_id == vehicle_id,
                MaintenanceLog.performed_date >= start,
                MaintenanceLog.performed_date <= end,
            )
        )

    # distance_km is the primary field; older rows may only carry odometer
    # readings, so fall back to the difference rather than reporting nothing.
    distance = trip.distance_km or 0.0
    if distance <= 0 and trip.odometer_start is not None and trip.odometer_end is not None:
        distance = max(trip.odometer_end - trip.odometer_start, 0.0)

    total = fuel_cost + maintenance_cost
    return {
        "fuel_cost": fuel_cost,
        "maintenance_cost": maintenance_cost,
        "total": total,
        "distance_km": distance,
        "cost_per_km": (total / distance) if distance > 0 else None,
        "start": start,
        "end": end,
        "open": open_trip,
    }
