"""Project (construction job/site) business logic.

A project is the cost-attribution layer: fuel, trips, maintenance and
expenses can each be booked to one optionally, so per-project cost reports
become possible. Validation lives here (name required, code unique,
end_date not before start_date); the models stay context-free.
"""
from datetime import date, datetime, time

from extensions import db
from app.models import (
    PROJECT_STATUSES,
    Expense,
    FuelLog,
    MaintenanceLog,
    Project,
    TripLog,
)

from .pagination import paginate
from .parsing import parse_date

# Codes like "PRJ-0001" issued when a code is left blank.
CODE_PREFIX = "PRJ"
CODE_DIGITS = 4


def resolve_project(raw) -> Project | None:
    """Blank means 'no project'; an id must resolve to a project.

    Shared by the trip/fuel/maintenance/expense services so the optional
    project dropdown behaves identically everywhere.
    """
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        project_id = int(raw)
    except ValueError:
        raise ValueError("Project not found") from None
    project = db.session.get(Project, project_id)
    if project is None:
        raise ValueError("Project not found")
    return project


def project_options() -> list[Project]:
    """Projects for the optional dropdown — one lightweight query, no COUNT.

    Ordered active-first so the jobs currently running sit at the top.
    """
    return Project.query.order_by(Project.status.asc(), Project.name.asc()).all()


def _code_taken(code: str, exclude_id: int | None = None) -> bool:
    """Case-insensitive uniqueness check — 'prj-0001' collides with 'PRJ-0001'."""
    query = Project.query.filter(db.func.lower(Project.code) == code.lower())
    if exclude_id is not None:
        query = query.filter(Project.id != exclude_id)
    return query.first() is not None


def _next_code() -> str:
    """First free ``PRJ-0001``-style code, skipping any already issued.

    Counts rather than scans for the next integer so issuance stays O(1); the
    skip loop only runs when a manual code consumed an auto-generated number.
    """
    n = Project.query.count() + 1
    while True:
        candidate = f"{CODE_PREFIX}-{n:0{CODE_DIGITS}d}"
        if not _code_taken(candidate):
            return candidate
        n += 1


def _code_from(data: dict, project: Project | None = None) -> str:
    raw = str(data.get("code") or "").strip()
    if raw:
        if _code_taken(raw, exclude_id=project.id if project else None):
            raise ValueError("A project with this code already exists")
        return raw.upper()
    if project is not None and project.code:
        return project.code
    return _next_code()


def _validate_dates(start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise ValueError("End date cannot be before start date")


def list_projects(
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list, int, int]:
    query = Project.query
    if status:
        query = query.filter(Project.status == status)
    if q:
        pattern = f"%{q.strip()}%"
        query = query.filter(
            db.or_(
                Project.name.ilike(pattern),
                Project.code.ilike(pattern),
                Project.client.ilike(pattern),
                Project.location.ilike(pattern),
            )
        )
    query = query.order_by(Project.status.asc(), Project.name.asc())
    return paginate(query, page, per_page)


def get_project(project_id: int) -> Project:
    project = db.session.get(Project, project_id)
    if project is None:
        raise LookupError(f"Project {project_id} not found")
    return project


def create_project(data: dict) -> Project:
    try:
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("Project name is required")

        status = str(data.get("status") or "").strip()
        if status and status not in PROJECT_STATUSES:
            raise ValueError("Invalid project status")

        start_date = parse_date(data.get("start_date"), "start_date")
        end_date = parse_date(data.get("end_date"), "end_date")
        _validate_dates(start_date, end_date)

        project = Project(
            name=name,
            code=_code_from(data),
            client=str(data.get("client") or "").strip() or None,
            location=str(data.get("location") or "").strip() or None,
            start_date=start_date,
            end_date=end_date,
            status=status or "planned",
            notes=data.get("notes") or None,
        )
        db.session.add(project)
        db.session.commit()
        return project
    except Exception:
        db.session.rollback()
        raise


def update_project(project_id: int, data: dict) -> Project:
    try:
        project = get_project(project_id)

        if "name" in data:
            name = str(data.get("name") or "").strip()
            if not name:
                raise ValueError("Project name is required")
            project.name = name
        if "code" in data:
            project.code = _code_from(data, project)
        if "client" in data:
            project.client = str(data.get("client") or "").strip() or None
        if "location" in data:
            project.location = str(data.get("location") or "").strip() or None
        if "start_date" in data:
            project.start_date = parse_date(data.get("start_date"), "start_date")
        if "end_date" in data:
            project.end_date = parse_date(data.get("end_date"), "end_date")
        _validate_dates(project.start_date, project.end_date)
        if "status" in data and str(data.get("status") or "").strip():
            status = str(data.get("status")).strip()
            if status not in PROJECT_STATUSES:
                raise ValueError("Invalid project status")
            project.status = status
        if "notes" in data:
            project.notes = data.get("notes") or None

        db.session.commit()
        return project
    except Exception:
        db.session.rollback()
        raise


def linked_counts(project_id: int) -> dict[str, int]:
    """How many records still point at this project, per type."""
    return {
        "trips": TripLog.query.filter_by(project_id=project_id).count(),
        "fuel": FuelLog.query.filter_by(project_id=project_id).count(),
        "maintenance": MaintenanceLog.query.filter_by(project_id=project_id).count(),
        "expenses": Expense.query.filter_by(project_id=project_id).count(),
    }


def delete_project(project_id: int) -> None:
    """Delete a project — blocked while cost records still link to it.

    The links would survive (SET NULL), but that silently strips cost
    history from the reports, so the user must unlink deliberately first.
    """
    try:
        project = get_project(project_id)
        counts = linked_counts(project_id)
        linked = sum(counts.values())
        if linked:
            parts = [f"{n} {label}" for label, n in counts.items() if n]
            raise ValueError(
                "Cannot delete: this project is still linked to "
                + ", ".join(parts)
                + ". Remove the project from those records first."
            )
        db.session.delete(project)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def project_cost_report(project_id: int, date_from=None, date_to=None) -> dict:
    """Every cost booked to a project over an optional date window.

    The four record types each carry their own date field (fuel_date,
    performed_date, trip start, expense_date), so the window is applied
    per type. Trips are counted with their distance; they carry no direct
    cost, but distance is what fuel and maintenance were burned to cover.
    """
    project = get_project(project_id)

    fuel_q = FuelLog.query.filter(FuelLog.project_id == project.id)
    maint_q = MaintenanceLog.query.filter(MaintenanceLog.project_id == project.id)
    trip_q = TripLog.query.filter(TripLog.project_id == project.id)
    expense_q = Expense.query.filter(Expense.project_id == project.id)

    if date_from not in (None, ""):
        d = parse_date(date_from, "date_from")
        fuel_q = fuel_q.filter(FuelLog.fuel_date >= d)
        maint_q = maint_q.filter(MaintenanceLog.performed_date >= d)
        trip_q = trip_q.filter(TripLog.start_time >= datetime.combine(d, time.min))
        expense_q = expense_q.filter(Expense.expense_date >= d)
    if date_to not in (None, ""):
        d = parse_date(date_to, "date_to")
        fuel_q = fuel_q.filter(FuelLog.fuel_date <= d)
        maint_q = maint_q.filter(MaintenanceLog.performed_date <= d)
        trip_q = trip_q.filter(TripLog.start_time <= datetime.combine(d, time.max))
        expense_q = expense_q.filter(Expense.expense_date <= d)

    fuel_logs = fuel_q.order_by(FuelLog.fuel_date.asc(), FuelLog.id.asc()).all()
    maintenance_logs = maint_q.order_by(
        MaintenanceLog.performed_date.asc(), MaintenanceLog.id.asc()
    ).all()
    trips = trip_q.order_by(TripLog.start_time.asc(), TripLog.id.asc()).all()
    expenses = expense_q.order_by(Expense.expense_date.asc(), Expense.id.asc()).all()

    fuel_total = sum(log.computed_total for log in fuel_logs)
    fuel_liters = sum(log.liters or 0 for log in fuel_logs)
    maintenance_total = sum(log.cost or 0 for log in maintenance_logs)
    expense_total = sum(row.amount or 0 for row in expenses)
    distance_km = sum(
        trip.distance_km
        or (
            trip.odometer_end - trip.odometer_start
            if trip.odometer_start is not None and trip.odometer_end is not None
            else 0.0
        )
        for trip in trips
    )

    by_category: dict[str, float] = {}
    for row in expenses:
        by_category[row.category] = by_category.get(row.category, 0.0) + (row.amount or 0)

    total = fuel_total + maintenance_total + expense_total
    return {
        "project": project,
        "fuel_logs": fuel_logs,
        "maintenance_logs": maintenance_logs,
        "trips": trips,
        "expenses": expenses,
        "fuel_total": fuel_total,
        "fuel_liters": fuel_liters,
        "maintenance_total": maintenance_total,
        "expense_total": expense_total,
        "expense_by_category": by_category,
        "distance_km": distance_km,
        "total": total,
        "cost_per_km": (total / distance_km) if distance_km > 0 else None,
    }
