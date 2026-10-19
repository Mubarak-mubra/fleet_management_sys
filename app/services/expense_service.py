"""Expense business logic.

Covers fleet costs that are neither fuel nor maintenance — insurance,
registration, wages, parking, tolls, washing, fines, office overhead, parts.
"""
from datetime import date

from extensions import db
from app.models import EXPENSE_CATEGORIES, Expense, Vehicle

from .pagination import paginate
from .parsing import parse_date, parse_float
from .project_service import resolve_project


def _resolve_vehicle(raw) -> Vehicle | None:
    """Blank means fleet-wide (no vehicle); an id must resolve to a vehicle."""
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        vehicle_id = int(raw)
    except ValueError:
        raise ValueError("Vehicle not found") from None
    vehicle = db.session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise ValueError("Vehicle not found")
    return vehicle


def expense_options() -> list[Vehicle]:
    """Vehicles for the optional dropdown — one lightweight query, no COUNT."""
    return Vehicle.query.order_by(Vehicle.status.asc(), Vehicle.name.asc()).all()


def list_expenses(
    vehicle_id: int | None = None,
    category: str | None = None,
    date_from: date | str | None = None,
    date_to: date | str | None = None,
    page: int = 1,
    per_page: int = 15,
) -> tuple[list, int, int]:
    query = Expense.query
    if vehicle_id:
        query = query.filter(Expense.vehicle_id == vehicle_id)
    if category:
        query = query.filter(Expense.category == category)
    if date_from not in (None, ""):
        query = query.filter(Expense.expense_date >= parse_date(date_from, "date_from"))
    if date_to not in (None, ""):
        query = query.filter(Expense.expense_date <= parse_date(date_to, "date_to"))
    query = query.order_by(Expense.expense_date.desc())
    return paginate(query, page, per_page)


def get_expense(expense_id: int) -> Expense:
    expense = db.session.get(Expense, expense_id)
    if expense is None:
        raise LookupError(f"Expense {expense_id} not found")
    return expense


def create_expense(data: dict) -> Expense:
    try:
        expense_date = parse_date(data.get("expense_date"), "expense_date")
        if expense_date is None:
            raise ValueError("Expense date is required")

        description = str(data.get("description") or "").strip()
        if not description:
            raise ValueError("Description is required")

        amount = parse_float(data.get("amount"), "amount")
        if amount is None:
            raise ValueError("Amount is required")
        if amount < 0:
            raise ValueError("Amount cannot be negative")

        expense = Expense(
            expense_date=expense_date,
            description=description,
            amount=amount,
            vehicle=_resolve_vehicle(data.get("vehicle_id")),
            project=resolve_project(data.get("project_id")),
        )

        category = str(data.get("category") or "").strip()
        if category:
            if category not in EXPENSE_CATEGORIES:
                raise ValueError("Invalid expense category")
            expense.category = category

        expense.vendor = str(data.get("vendor") or "").strip() or None
        expense.payment_method = str(data.get("payment_method") or "").strip() or None
        expense.receipt_ref = str(data.get("receipt_ref") or "").strip() or None
        expense.notes = data.get("notes") or None

        db.session.add(expense)
        db.session.commit()
        return expense
    except Exception:
        db.session.rollback()
        raise


def update_expense(expense_id: int, data: dict) -> Expense:
    try:
        expense = get_expense(expense_id)

        if "expense_date" in data:
            expense_date = parse_date(data.get("expense_date"), "expense_date")
            if expense_date is None:
                raise ValueError("Expense date is required")
            expense.expense_date = expense_date
        if "description" in data:
            description = str(data.get("description") or "").strip()
            if not description:
                raise ValueError("Description is required")
            expense.description = description
        if "amount" in data:
            amount = parse_float(data.get("amount"), "amount")
            if amount is None:
                raise ValueError("Amount is required")
            if amount < 0:
                raise ValueError("Amount cannot be negative")
            expense.amount = amount

        if "vehicle_id" in data:
            expense.vehicle = _resolve_vehicle(data.get("vehicle_id"))

        if "project_id" in data:
            expense.project = resolve_project(data.get("project_id"))

        if "category" in data and str(data.get("category") or "").strip():
            category = str(data.get("category")).strip()
            if category not in EXPENSE_CATEGORIES:
                raise ValueError("Invalid expense category")
            expense.category = category

        if "vendor" in data:
            expense.vendor = str(data.get("vendor") or "").strip() or None
        if "payment_method" in data:
            expense.payment_method = str(data.get("payment_method") or "").strip() or None
        if "receipt_ref" in data:
            expense.receipt_ref = str(data.get("receipt_ref") or "").strip() or None
        if "notes" in data:
            expense.notes = data.get("notes") or None

        db.session.commit()
        return expense
    except Exception:
        db.session.rollback()
        raise


def delete_expense(expense_id: int) -> None:
    try:
        expense = get_expense(expense_id)
        db.session.delete(expense)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def expense_stats(vehicle_id: int | None = None, date_from=None, date_to=None) -> dict:
    query = Expense.query
    if vehicle_id:
        query = query.filter(Expense.vehicle_id == vehicle_id)
    if date_from not in (None, ""):
        query = query.filter(Expense.expense_date >= parse_date(date_from, "date_from"))
    if date_to not in (None, ""):
        query = query.filter(Expense.expense_date <= parse_date(date_to, "date_to"))
    rows = query.all()

    total = sum(row.amount or 0 for row in rows)
    by_category: dict[str, float] = {}
    for row in rows:
        by_category[row.category] = by_category.get(row.category, 0.0) + (row.amount or 0)

    return {
        "total": total,
        "count": len(rows),
        "by_category": by_category,
    }
