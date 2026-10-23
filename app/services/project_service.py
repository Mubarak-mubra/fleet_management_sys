"""Project (construction job/site) business logic.

A project is a reporting layer over work that actually happens to vehicles.
Trips and expenses can be booked to one, because a trip genuinely goes to a
site and a site permit genuinely belongs to it.

Fuel and maintenance are NOT bookable to a project — see their models. A
fill-up or a set of tyres serves whatever the vehicle does next, so nobody at
the pump can honestly name a project. The project report derives those costs
from trip distance instead, and labels them as estimates.

Validation lives here (name required, code unique, end_date not before
start_date); the models stay context-free.
"""
from datetime import date, datetime, time

from extensions import db
from app.models import (
    PROJECT_STATUSES,
    Expense,
    MaintenanceLog,
    Project,
    TripLog,
    Vehicle,
)

from .fuel_service import fuel_efficiency, fuel_stats
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


def trip_distance(trip: TripLog) -> float:
    """Distance a trip actually covered.

    The recorded distance wins when present. Otherwise fall back to the
    odometer gap, which is the more trustworthy ruler — but only when both
    readings exist and move forwards (a swapped or reset pair would report
    hundreds of negative kilometres).
    """
    if trip.distance_km:
        return float(trip.distance_km)
    if trip.odometer_start is None or trip.odometer_end is None:
        return 0.0
    gap = float(trip.odometer_end) - float(trip.odometer_start)
    return gap if gap > 0 else 0.0


def linked_counts(project_id: int) -> dict[str, int]:
    """How many records still point at this project, per type.

    Only trips and expenses carry a project. Fuel and maintenance are vehicle
    costs with no project to unlink (see their models), and the project report
    derives fuel from trips, so nothing there blocks a delete either.
    """
    return {
        "trips": TripLog.query.filter_by(project_id=project_id).count(),
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
    """What this project cost, over an optional date window.

    Fuel and maintenance are deliberately NOT booked to a project anywhere in
    this system (see their models): a fill-up or a set of tyres serves whatever
    the vehicle does next, so nobody at the pump can honestly name a project.
    Booking them here would mean guessing.

    Instead the fuel line is derived from trips, which DO carry a project:

        fuel_liters  = distance driven here / the vehicle's measured km/L
        fuel_total   = those liters x the fleet's average cost per liter

    Both inputs are real, measured numbers — odometer distance from the trips
    themselves, and efficiency from consecutive fill-ups. Only the split is
    arithmetic, which makes this an ESTIMATE, labelled as one throughout.

    The known limit is unrecorded driving. A yard run never entered as a trip
    burns real fuel but vanishes from the vehicle's recorded distance, so the
    project's share of that vehicle's MAINTENANCE (project km / all recorded
    km) inflates and leans high by exactly that much. Fuel is safer: it is
    charged only for distance actually recorded against the project, so
    missing trips understate fuel rather than inflate it.

    Maintenance is likewise estimated, by each working vehicle's share of its
    own kilometres — see _derive_project_costs.
    """
    project = get_project(project_id)

    trip_q = TripLog.query.filter(TripLog.project_id == project.id)
    expense_q = Expense.query.filter(Expense.project_id == project.id)

    if date_from not in (None, ""):
        d = parse_date(date_from, "date_from")
        trip_q = trip_q.filter(TripLog.start_time >= datetime.combine(d, time.min))
        expense_q = expense_q.filter(Expense.expense_date >= d)
    if date_to not in (None, ""):
        d = parse_date(date_to, "date_to")
        trip_q = trip_q.filter(TripLog.start_time <= datetime.combine(d, time.max))
        expense_q = expense_q.filter(Expense.expense_date <= d)

    trips = trip_q.order_by(TripLog.start_time.asc(), TripLog.id.asc()).all()
    expenses = expense_q.order_by(Expense.expense_date.asc(), Expense.id.asc()).all()

    distance_km = sum(trip_distance(trip) for trip in trips)
    expense_total = sum(row.amount or 0 for row in expenses)

    fuel_liters, fuel_total, maintenance_total, vehicle_rows = _derive_project_costs(
        trips, date_from, date_to
    )

    by_category: dict[str, float] = {}
    for row in expenses:
        by_category[row.category] = by_category.get(row.category, 0.0) + (row.amount or 0)

    total = fuel_total + maintenance_total + expense_total
    return {
        "project": project,
        "trips": trips,
        "expenses": expenses,
        "fuel_liters": fuel_liters,
        "fuel_total": fuel_total,
        "fuel_estimate": True,
        "maintenance_total": maintenance_total,
        "maintenance_estimate": True,
        "vehicle_rows": vehicle_rows,
        "expense_total": expense_total,
        "expense_by_category": by_category,
        "distance_km": distance_km,
        "total": total,
        "cost_per_km": (total / distance_km) if distance_km > 0 else None,
    }


def _derive_project_costs(
    trips: list, date_from=None, date_to=None
) -> tuple[float, float, float, list[dict]]:
    """Vehicle costs this project can claim, broken out per vehicle.

    Returns (fuel_liters, fuel_total, maintenance_total, per_vehicle_rows).

    FUEL — distance done here / that vehicle's OWN measured km/L. Each
    vehicle is charged at its own fill-to-fill efficiency (consecutive
    fill-ups give odometer gap over liters added), so a truck doing 2.2 km/L
    pays 2.2 and a thirsty grader pays its own rate. A vehicle with no usable
    efficiency figure yet still gets charged at the fleet average, so its
    trips are not silently free — that fallback is flagged on its row.

    MAINTENANCE — what the vehicle cost to maintain over the window,
    multiplied by the fraction of ITS OWN distance spent on this project. A
    truck that did 70% of its kilometres here carries 70% of its servicing
    cost here, capped at 100%. Wear follows kilometres, which is roughly true
    and never exactly.

    The per-vehicle rows are what make the estimate auditable: you can see
    which vehicle did the distance and what was charged for it, rather than
    being handed one unexplained total.
    """
    if not trips:
        return 0.0, 0.0, 0.0, []

    efficiency = fuel_efficiency()
    by_vehicle_eff = efficiency.get("by_vehicle", {})
    fleet_avg = efficiency.get("avg_km_per_liter") or 0.0
    # Money uses what this company actually pays, weighted by its own spend.
    cost_per_liter = fuel_stats().get("avg_cost_per_liter") or 0.0

    project_km: dict[int, float] = {}
    for trip in trips:
        project_km[trip.vehicle_id] = project_km.get(trip.vehicle_id, 0.0) + (
            trip_distance(trip)
        )

    fuel_liters = 0.0
    fuel_total = 0.0
    maintenance_total = 0.0
    rows: list[dict] = []

    for vehicle_id, km in project_km.items():
        entry = by_vehicle_eff.get(vehicle_id) or {}
        km_per_liter = float(entry["km_per_liter"] or 0) if entry else 0.0
        estimated_efficiency = not km_per_liter
        if not km_per_liter:
            km_per_liter = fleet_avg

        liters = (km / km_per_liter) if km_per_liter else 0.0
        fuel_cost = liters * cost_per_liter
        share = _maintenance_share(vehicle_id, km, date_from, date_to)

        fuel_liters += liters
        fuel_total += fuel_cost
        maintenance_total += share["cost"]
        rows.append(
            {
                "vehicle": db.session.get(Vehicle, vehicle_id),
                "km": km,
                "liters": liters,
                "fuel_cost": fuel_cost,
                "km_per_liter": km_per_liter or None,
                "estimated_efficiency": estimated_efficiency,
                "maintenance_cost": share["cost"],
                "maintenance_basis": share["basis"],
            }
        )

    rows.sort(key=lambda r: -r["km"])
    return fuel_liters, fuel_total, maintenance_total, rows


def _maintenance_share(
    vehicle_id: int, project_km: float, date_from=None, date_to=None
) -> dict:
    """This vehicle's maintenance, cut down to its share spent here.

    Returns the cut cost plus a human-readable basis string, so the report
    can say where the number came from ("70% of 1,240 USD, by 70% of km").
    """
    fleet_km = sum(
        trip_distance(t)
        for t in _window(
            TripLog.query.filter(TripLog.vehicle_id == vehicle_id),
            TripLog.start_time,
            date_from,
            date_to,
        ).all()
    )
    maint_cost = sum(
        log.cost or 0
        for log in _window(
            MaintenanceLog.query.filter(MaintenanceLog.vehicle_id == vehicle_id),
            MaintenanceLog.performed_date,
            date_from,
            date_to,
        ).all()
    )
    if not fleet_km or not maint_cost:
        return {"cost": 0.0, "basis": None}

    fraction = min(project_km / fleet_km, 1.0)
    return {
        "cost": maint_cost * fraction,
        "basis": {
            "fraction": fraction,
            "total_cost": maint_cost,
            "project_km": project_km,
            "fleet_km": fleet_km,
        },
    }


def _window(query, column, date_from, date_to):
    """Apply the same date window the trip query uses, to another model."""
    if date_from not in (None, ""):
        query = query.filter(column >= parse_date(date_from, "date_from"))
    if date_to not in (None, ""):
        query = query.filter(column <= parse_date(date_to, "date_to"))
    return query
