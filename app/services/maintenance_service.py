"""Maintenance business logic."""
from datetime import date

from extensions import db
from app.models import (
    MAINTENANCE_STATUSES,
    MAINTENANCE_TYPES,
    MaintenanceLog,
    Vehicle,
)

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


def list_maintenance(
    vehicle_id: int | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list, int, int]:
    query = MaintenanceLog.query
    if vehicle_id:
        query = query.filter(MaintenanceLog.vehicle_id == vehicle_id)
    if status:
        query = query.filter(MaintenanceLog.status == status)
    query = query.order_by(MaintenanceLog.performed_date.desc())
    return paginate(query, page, per_page)


def get_maintenance(maintenance_id: int) -> MaintenanceLog:
    log = db.session.get(MaintenanceLog, maintenance_id)
    if log is None:
        raise LookupError(f"Maintenance record {maintenance_id} not found")
    return log


def create_maintenance(data: dict) -> MaintenanceLog:
    try:
        vehicle = _resolve_vehicle(data.get("vehicle_id"))

        description = str(data.get("description") or "").strip()
        if not description:
            raise ValueError("Description is required")

        performed_date = parse_date(data.get("performed_date"), "performed_date")
        if performed_date is None:
            raise ValueError("Performed date is required")

        next_due_date = parse_date(data.get("next_due_date"), "next_due_date")
        if next_due_date is not None and next_due_date < performed_date:
            raise ValueError("next_due_date cannot be before performed_date")

        cost = parse_float(data.get("cost"), "cost", default=0.0)
        if cost is None:
            cost = 0.0
        if cost < 0:
            raise ValueError("Cost cannot be negative")

        maintenance_type = str(data.get("maintenance_type") or "").strip()
        if maintenance_type and maintenance_type not in MAINTENANCE_TYPES:
            raise ValueError("Invalid maintenance type")

        status = str(data.get("status") or "").strip()
        if status and status not in MAINTENANCE_STATUSES:
            raise ValueError("Invalid maintenance status")

        log = MaintenanceLog(
            vehicle_id=vehicle.id,
            project=resolve_project(data.get("project_id")),
            maintenance_type=maintenance_type or "service",
            description=description,
            performed_date=performed_date,
            next_due_date=next_due_date,
            cost=cost,
            vendor=str(data.get("vendor") or "").strip() or None,
            status=status or "completed",
            notes=data.get("notes") or None,
        )
        odometer = parse_float(data.get("odometer"), "odometer")
        if odometer is not None:
            log.odometer = odometer

        db.session.add(log)
        db.session.commit()
        return log
    except Exception:
        db.session.rollback()
        raise


def update_maintenance(maintenance_id: int, data: dict) -> MaintenanceLog:
    try:
        log = get_maintenance(maintenance_id)

        if "vehicle_id" in data:
            log.vehicle_id = _resolve_vehicle(data.get("vehicle_id")).id
        if "project_id" in data:
            log.project = resolve_project(data.get("project_id"))
        if "description" in data:
            description = str(data.get("description") or "").strip()
            if not description:
                raise ValueError("Description is required")
            log.description = description
        if "performed_date" in data:
            performed_date = parse_date(data.get("performed_date"), "performed_date")
            if performed_date is None:
                raise ValueError("Performed date is required")
            log.performed_date = performed_date
        if "next_due_date" in data:
            next_due_date = parse_date(data.get("next_due_date"), "next_due_date")
            if next_due_date is not None and next_due_date < log.performed_date:
                raise ValueError("next_due_date cannot be before performed_date")
            log.next_due_date = next_due_date
        if "cost" in data:
            cost = parse_float(data.get("cost"), "cost", default=0.0)
            if cost is None:
                cost = 0.0
            if cost < 0:
                raise ValueError("Cost cannot be negative")
            log.cost = cost
        if "maintenance_type" in data and str(data.get("maintenance_type") or "").strip():
            maintenance_type = str(data.get("maintenance_type")).strip()
            if maintenance_type not in MAINTENANCE_TYPES:
                raise ValueError("Invalid maintenance type")
            log.maintenance_type = maintenance_type
        if "status" in data and str(data.get("status") or "").strip():
            status = str(data.get("status")).strip()
            if status not in MAINTENANCE_STATUSES:
                raise ValueError("Invalid maintenance status")
            log.status = status
        if "vendor" in data:
            log.vendor = str(data.get("vendor") or "").strip() or None
        if "odometer" in data:
            odometer = parse_float(data.get("odometer"), "odometer")
            if odometer is not None:
                log.odometer = odometer
        if "notes" in data:
            log.notes = data.get("notes") or None

        db.session.commit()
        return log
    except Exception:
        db.session.rollback()
        raise


def delete_maintenance(maintenance_id: int) -> None:
    try:
        log = get_maintenance(maintenance_id)
        db.session.delete(log)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def overdue_items(vehicle_id: int | None = None) -> list[MaintenanceLog]:
    query = MaintenanceLog.query.filter(
        MaintenanceLog.next_due_date.isnot(None),
        MaintenanceLog.next_due_date < date.today(),
        MaintenanceLog.status != "completed",
    )
    if vehicle_id:
        query = query.filter(MaintenanceLog.vehicle_id == vehicle_id)
    return query.order_by(MaintenanceLog.next_due_date.asc()).all()


def maintenance_stats(vehicle_id: int | None = None) -> dict:
    query = MaintenanceLog.query
    if vehicle_id:
        query = query.filter(MaintenanceLog.vehicle_id == vehicle_id)
    logs = query.all()

    total_cost = sum(log.cost or 0 for log in logs)
    by_type: dict[str, float] = {}
    for log in logs:
        by_type[log.maintenance_type] = by_type.get(log.maintenance_type, 0.0) + (log.cost or 0)

    overdue_count = len(overdue_items(vehicle_id))
    upcoming = [
        log
        for log in logs
        if log.next_due_date is not None and log.next_due_date >= date.today()
    ]
    upcoming.sort(key=lambda log: log.next_due_date)

    return {
        "total_cost": total_cost,
        "by_type": by_type,
        "overdue_count": overdue_count,
        "upcoming": upcoming,
    }
