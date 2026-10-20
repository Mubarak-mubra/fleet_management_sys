"""Vehicle business logic."""
from extensions import db
from app.models import VEHICLE_STATUSES, TripLog, Vehicle

from .pagination import paginate
from .parsing import parse_float
from .vehicle_type_service import find_registered_name


def _required(data: dict, key: str, label: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    return value


def _plate_exists(plate: str, exclude_id: int | None = None) -> bool:
    query = Vehicle.query.filter(db.func.lower(Vehicle.plate_number) == plate.lower())
    if exclude_id is not None:
        query = query.filter(Vehicle.id != exclude_id)
    return query.first() is not None


def vehicle_options() -> list[Vehicle]:
    """All vehicles for form dropdowns — one lightweight query, no COUNT."""
    return Vehicle.query.order_by(Vehicle.status.asc(), Vehicle.name.asc()).all()


def list_vehicles(
    status: str | None = None, q: str | None = None, page: int = 1, per_page: int = 15
) -> tuple[list, int, int]:
    query = Vehicle.query
    if status:
        query = query.filter(Vehicle.status == status)
    if q and str(q).strip():
        pattern = f"%{str(q).strip()}%"
        query = query.filter(
            db.or_(
                Vehicle.name.ilike(pattern),
                Vehicle.plate_number.ilike(pattern),
                Vehicle.make.ilike(pattern),
                Vehicle.model.ilike(pattern),
            )
        )
    query = query.order_by(Vehicle.status.asc(), Vehicle.name.asc())
    return paginate(query, page, per_page)


def get_vehicle(vehicle_id: int) -> Vehicle:
    vehicle = db.session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise LookupError(f"Vehicle {vehicle_id} not found")
    return vehicle


def create_vehicle(data: dict) -> Vehicle:
    try:
        name = _required(data, "name", "Name")
        plate = _required(data, "plate_number", "Plate number")
        if _plate_exists(plate):
            raise ValueError("Plate number already exists")

        vehicle = Vehicle(name=name, plate_number=plate)

        submitted_type = str(data.get("vehicle_type") or "").strip()
        if submitted_type:
            canonical = find_registered_name(submitted_type)
            if canonical is None:
                raise ValueError(
                    "Unknown vehicle type — add it under "
                    "Vehicles → Vehicle Types first"
                )
            vehicle.vehicle_type = canonical

        status = str(data.get("status") or "").strip()
        if status:
            if status not in VEHICLE_STATUSES:
                raise ValueError("Invalid vehicle status")
            vehicle.status = status

        year_raw = str(data.get("year") or "").strip()
        if year_raw:
            try:
                year = int(year_raw)
            except ValueError:
                raise ValueError("Invalid year") from None
            if not 1900 <= year <= 2100:
                raise ValueError("Year must be between 1900 and 2100")
            vehicle.year = year

        vehicle.make = str(data.get("make") or "").strip() or None
        vehicle.model = str(data.get("model") or "").strip() or None
        vehicle.notes = data.get("notes") or None

        odometer = parse_float(data.get("odometer"), "odometer")
        if odometer is not None:
            vehicle.odometer = odometer
        capacity = parse_float(data.get("fuel_capacity_liters"), "fuel_capacity_liters")
        if capacity is not None:
            vehicle.fuel_capacity_liters = capacity

        db.session.add(vehicle)
        db.session.commit()
        return vehicle
    except Exception:
        db.session.rollback()
        raise


def update_vehicle(vehicle_id: int, data: dict) -> Vehicle:
    try:
        vehicle = get_vehicle(vehicle_id)

        if "name" in data:
            vehicle.name = _required(data, "name", "Name")
        if "plate_number" in data:
            plate = _required(data, "plate_number", "Plate number")
            if _plate_exists(plate, exclude_id=vehicle.id):
                raise ValueError("Plate number already exists")
            vehicle.plate_number = plate

        if "vehicle_type" in data and str(data.get("vehicle_type") or "").strip():
            submitted = str(data.get("vehicle_type")).strip()
            canonical = find_registered_name(submitted)
            if canonical is None and submitted != (vehicle.vehicle_type or "").strip():
                raise ValueError(
                    "Unknown vehicle type — add it under "
                    "Vehicles → Vehicle Types first"
                )
            # Canonical registered spelling; a legacy stored value that is
            # unchanged is allowed to stay as-is.
            vehicle.vehicle_type = canonical or submitted

        if "status" in data and str(data.get("status") or "").strip():
            status = str(data.get("status")).strip()
            if status not in VEHICLE_STATUSES:
                raise ValueError("Invalid vehicle status")
            vehicle.status = status

        if "year" in data and str(data.get("year") or "").strip():
            year_raw = str(data.get("year")).strip()
            try:
                year = int(year_raw)
            except ValueError:
                raise ValueError("Invalid year") from None
            if not 1900 <= year <= 2100:
                raise ValueError("Year must be between 1900 and 2100")
            vehicle.year = year

        if "make" in data:
            vehicle.make = str(data.get("make") or "").strip() or None
        if "model" in data:
            vehicle.model = str(data.get("model") or "").strip() or None
        if "notes" in data:
            vehicle.notes = data.get("notes") or None
        if "odometer" in data:
            odometer = parse_float(data.get("odometer"), "odometer")
            if odometer is not None:
                vehicle.odometer = odometer
        if "fuel_capacity_liters" in data:
            capacity = parse_float(data.get("fuel_capacity_liters"), "fuel_capacity_liters")
            if capacity is not None:
                vehicle.fuel_capacity_liters = capacity

        db.session.commit()
        return vehicle
    except Exception:
        db.session.rollback()
        raise


def delete_vehicle(vehicle_id: int) -> None:
    try:
        vehicle = get_vehicle(vehicle_id)
        open_trip = TripLog.query.filter(
            TripLog.vehicle_id == vehicle.id,
            TripLog.status.in_(("planned", "in_progress")),
        ).first()
        if open_trip is not None:
            raise ValueError("Cannot delete vehicle with an active trip")
        db.session.delete(vehicle)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def vehicle_summary(vehicle_id: int) -> dict:
    vehicle = get_vehicle(vehicle_id)
    trips = list(vehicle.trips)
    open_trips = sum(1 for trip in trips if trip.status in ("planned", "in_progress"))
    last_trip = max(trips, key=lambda trip: trip.start_time, default=None)
    return {
        "trips": len(trips),
        "total_fuel_liters": vehicle.total_fuel_liters,
        "total_fuel_cost": sum(log.computed_total for log in vehicle.fuel_logs),
        "total_maintenance_cost": vehicle.total_maintenance_cost,
        "last_trip": last_trip,
        "open_trips": open_trips,
    }
