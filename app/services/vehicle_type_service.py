"""Vehicle type registry — the fleet's own list of machine types.

Users manage the list on the Vehicles -> Vehicle Types subtab; the vehicle
form's Type dropdown is built from these rows, and creating a vehicle with
an unregistered type is rejected so the registry stays the source of truth.
"""
from sqlalchemy import func

from extensions import db
from app.models import Vehicle, VehicleType


def type_options() -> list[str]:
    """Registered type names for form dropdowns, sorted."""
    return sorted((t.name for t in VehicleType.query.all()), key=str.lower)


def find_registered_name(submitted: str) -> str | None:
    """Case-insensitive match against the registry.

    Returns the canonical registered spelling ("tipper" -> "Tipper"), or
    None when the value was never registered.
    """
    value = str(submitted or "").strip()
    if not value:
        return None
    lowered = value.lower()
    for name in type_options():
        if name.lower() == lowered:
            return name
    return None


def list_types() -> list[dict]:
    """Every registered type with how many vehicles currently use it.

    Usage is matched case-insensitively so legacy rows ("tipper" typed
    before registration) still count against "Tipper".
    """
    usage: dict[str, int] = {}
    rows = (
        db.session.query(Vehicle.vehicle_type, func.count(Vehicle.id))
        .group_by(Vehicle.vehicle_type)
        .all()
    )
    for name, count in rows:
        key = (name or "").strip().lower()
        usage[key] = usage.get(key, 0) + count
    return [
        {"type": t, "count": usage.get(t.name.lower(), 0)}
        for t in VehicleType.query.order_by(VehicleType.name.asc()).all()
    ]


def create_type(data: dict) -> VehicleType:
    try:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Type name is required")
        if len(name) > 50:
            raise ValueError("Type name must be 50 characters or fewer")
        if find_registered_name(name):
            raise ValueError(f"Type '{name}' already exists")
        vehicle_type = VehicleType(name=name)
        db.session.add(vehicle_type)
        db.session.commit()
        return vehicle_type
    except Exception:
        db.session.rollback()
        raise


def delete_type(type_id: int) -> None:
    """Delete a type — blocked while vehicles still reference it, so no
    vehicle ever ends up with a type that no longer exists."""
    try:
        vehicle_type = db.session.get(VehicleType, type_id)
        if vehicle_type is None:
            raise LookupError(f"Vehicle type {type_id} not found")
        users = Vehicle.query.filter(
            func.lower(Vehicle.vehicle_type) == vehicle_type.name.lower()
        ).count()
        if users:
            noun = "vehicle uses" if users == 1 else "vehicles use"
            raise ValueError(
                f"{users} {noun} this type — reassign those vehicles first"
            )
        db.session.delete(vehicle_type)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
