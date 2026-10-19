"""Driver business logic.

Drivers register once here instead of having their names typed into trip
forms. Each driver is issued a unique fleet card (``card_code``).
"""
from extensions import db
from app.models import CARD_STATUSES, DRIVER_STATUSES, Driver, TripLog

from .pagination import paginate

# Codes like "DRV-0001" issued when a card number is left blank.
CARD_PREFIX = "DRV"
CARD_DIGITS = 4


def _required(data: dict, key: str, label: str) -> str:
    value = str(data.get(key) or "").strip()
    if not value:
        raise ValueError(f"{label} is required")
    return value


def _card_taken(card_code: str, exclude_id: int | None = None) -> bool:
    """Case-insensitive uniqueness check — 'drv-0001' collides with 'DRV-0001'."""
    query = Driver.query.filter(db.func.lower(Driver.card_code) == card_code.lower())
    if exclude_id is not None:
        query = query.filter(Driver.id != exclude_id)
    return query.first() is not None


def _next_card_code() -> str:
    """First free ``DRV-0001``-style code, skipping any already issued.

    Counts rather than scans for the next integer so issuance stays O(1); the
    skip loop only runs when a manual card consumed an auto-generated number.
    """
    n = Driver.query.count() + 1
    while True:
        candidate = f"{CARD_PREFIX}-{n:0{CARD_DIGITS}d}"
        if not _card_taken(candidate):
            return candidate
        n += 1


def _validate_phone(phone: str | None) -> str | None:
    if phone is None:
        return None
    phone = str(phone).strip()
    if not phone:
        return None
    digits = phone.replace("+", "").replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not digits.isdigit() or not 7 <= len(digits) <= 15:
        raise ValueError("Phone number must be 7-15 digits")
    return phone


def driver_options() -> list[Driver]:
    """All drivers for form dropdowns — one lightweight query, no COUNT.

    Unavailable drivers sort last so the obvious pick is a usable one.
    """
    return Driver.query.order_by(Driver.status.asc(), Driver.name.asc()).all()


def list_drivers(
    status: str | None = None, q: str | None = None, page: int = 1, per_page: int = 15
) -> tuple[list, int, int]:
    query = Driver.query
    if status:
        query = query.filter(Driver.status == status)
    if q and str(q).strip():
        pattern = f"%{str(q).strip()}%"
        query = query.filter(
            db.or_(
                Driver.name.ilike(pattern),
                Driver.card_code.ilike(pattern),
                Driver.phone.ilike(pattern),
                Driver.license_number.ilike(pattern),
            )
        )
    query = query.order_by(Driver.status.asc(), Driver.name.asc())
    return paginate(query, page, per_page)


def get_driver(driver_id: int) -> Driver:
    driver = db.session.get(Driver, driver_id)
    if driver is None:
        raise LookupError(f"Driver {driver_id} not found")
    return driver


def _card_code_from(data: dict, driver: Driver | None = None) -> str:
    """Use the submitted card code, else reuse the driver's, else issue one."""
    raw = str(data.get("card_code") or "").strip()
    if not raw:
        if driver is not None and driver.card_code:
            return driver.card_code
        return _next_card_code()
    if len(raw) > 30:
        raise ValueError("Card code must be at most 30 characters")
    if _card_taken(raw, exclude_id=driver.id if driver else None):
        raise ValueError("Card code already assigned to another driver")
    return raw


def create_driver(data: dict) -> Driver:
    try:
        name = _required(data, "name", "Name")

        driver = Driver(name=name)
        driver.card_code = _card_code_from(data)

        phone = _validate_phone(data.get("phone"))
        driver.phone = phone
        driver.license_number = str(data.get("license_number") or "").strip() or None
        driver.notes = data.get("notes") or None

        status = str(data.get("status") or "").strip()
        if status:
            if status not in DRIVER_STATUSES:
                raise ValueError("Invalid driver status")
            driver.status = status

        card_status = str(data.get("card_status") or "").strip()
        if card_status:
            if card_status not in CARD_STATUSES:
                raise ValueError("Invalid card status")
            driver.card_status = card_status

        db.session.add(driver)
        db.session.commit()
        return driver
    except Exception:
        db.session.rollback()
        raise


def update_driver(driver_id: int, data: dict) -> Driver:
    try:
        driver = get_driver(driver_id)

        if "name" in data:
            driver.name = _required(data, "name", "Name")

        if "card_code" in data:
            driver.card_code = _card_code_from(data, driver)

        if "phone" in data:
            driver.phone = _validate_phone(data.get("phone"))
        if "license_number" in data:
            driver.license_number = str(data.get("license_number") or "").strip() or None
        if "notes" in data:
            driver.notes = data.get("notes") or None

        if "status" in data and str(data.get("status") or "").strip():
            status = str(data.get("status")).strip()
            if status not in DRIVER_STATUSES:
                raise ValueError("Invalid driver status")
            driver.status = status

        if "card_status" in data and str(data.get("card_status") or "").strip():
            card_status = str(data.get("card_status")).strip()
            if card_status not in CARD_STATUSES:
                raise ValueError("Invalid card status")
            driver.card_status = card_status

        db.session.commit()
        return driver
    except Exception:
        db.session.rollback()
        raise


def delete_driver(driver_id: int) -> None:
    try:
        driver = get_driver(driver_id)
        open_trip = TripLog.query.filter(
            TripLog.driver_id == driver.id,
            TripLog.status.in_(("planned", "in_progress")),
        ).first()
        if open_trip is not None:
            raise ValueError("Cannot delete driver with an active trip")
        # Past trips keep their driver_name snapshot; the FK is SET NULL.
        db.session.delete(driver)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def driver_summary(driver_id: int) -> dict:
    driver = get_driver(driver_id)
    trips = list(driver.trips)
    open_trips = sum(1 for trip in trips if trip.status in ("planned", "in_progress"))
    last_trip = max(trips, key=lambda trip: trip.start_time, default=None)
    return {
        "trips": len(trips),
        "open_trips": open_trips,
        "last_trip": last_trip,
        "total_distance_km": sum(trip.distance_km or 0 for trip in trips),
    }
