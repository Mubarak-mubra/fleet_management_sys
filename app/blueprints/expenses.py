from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import expense_service, project_service, vehicle_service

bp = Blueprint("expenses", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    vehicle_id = request.args.get("vehicle_id", type=int) or None
    category = request.args.get("category") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    try:
        items, total, pages = expense_service.list_expenses(
            vehicle_id=vehicle_id,
            category=category,
            date_from=date_from,
            date_to=date_to,
            page=page,
        )
        stats = expense_service.expense_stats(
            vehicle_id=vehicle_id, date_from=date_from, date_to=date_to
        )
    except ValueError as exc:
        flash(str(exc), "error")
        items, total, pages = [], 0, 1
        stats = {"total": 0, "count": 0, "by_category": {}}
    return render_template(
        "expenses/list.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        vehicle_id=vehicle_id,
        category=category,
        date_from=date_from,
        date_to=date_to,
        vehicles=expense_service.expense_options(),
        stats=stats,
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            expense = expense_service.create_expense(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("expenses.create"))
        flash(f"Expense of {expense.amount} created", "success")
        return redirect(url_for("expenses.list"))
    return render_template(
        "expenses/form.html",
        form_data={},
        mode="create",
        vehicles=expense_service.expense_options(),
        projects=project_service.project_options(),
    )


@bp.route("/<int:expense_id>/edit", methods=["GET", "POST"])
def edit(expense_id):
    try:
        expense = expense_service.get_expense(expense_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            expense = expense_service.update_expense(expense_id, request.form.to_dict())
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("expenses.edit", expense_id=expense_id))
        flash("Expense updated", "success")
        return redirect(url_for("expenses.list"))
    form_data = {
        "vehicle_id": expense.vehicle_id,
        "project_id": expense.project_id,
        "expense_date": expense.expense_date.strftime("%Y-%m-%d") if expense.expense_date else "",
        "category": expense.category,
        "description": expense.description,
        "amount": expense.amount,
        "vendor": expense.vendor or "",
        "payment_method": expense.payment_method or "",
        "receipt_ref": expense.receipt_ref or "",
        "notes": expense.notes or "",
    }
    return render_template(
        "expenses/form.html",
        form_data=form_data,
        mode="edit",
        expense=expense,
        vehicles=expense_service.expense_options(),
        projects=project_service.project_options(),
    )


@bp.route("/<int:expense_id>/delete", methods=["POST"])
def delete(expense_id):
    try:
        expense_service.delete_expense(expense_id)
    except LookupError:
        abort(404)
    flash("Expense deleted", "success")
    return redirect(url_for("expenses.list"))
