from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from app.services import driver_service

bp = Blueprint("drivers", __name__)


@bp.route("/")
def list():
    page = request.args.get("page", 1, type=int)
    status = request.args.get("status") or None
    q = request.args.get("q") or None
    items, total, pages = driver_service.list_drivers(
        status=status, q=q, page=page
    )
    return render_template(
        "drivers/list.html",
        items=items,
        total=total,
        pages=pages,
        page=page,
        status=status,
        q=q,
        mode="list",
    )


@bp.route("/new", methods=["GET", "POST"])
def create():
    if request.method == "POST":
        try:
            driver = driver_service.create_driver(request.form.to_dict())
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("drivers.create"))
        flash(f"Driver {driver.name} registered with card {driver.card_code}", "success")
        return redirect(url_for("drivers.list"))
    return render_template("drivers/form.html", form_data={}, mode="create")


@bp.route("/<int:driver_id>/")
def detail(driver_id):
    try:
        driver = driver_service.get_driver(driver_id)
    except LookupError:
        abort(404)
    summary = driver_service.driver_summary(driver_id)
    return render_template(
        "drivers/detail.html",
        driver=driver,
        summary=summary,
        mode="detail",
        form_data={},
    )


@bp.route("/<int:driver_id>/edit", methods=["GET", "POST"])
def edit(driver_id):
    try:
        driver = driver_service.get_driver(driver_id)
    except LookupError:
        abort(404)
    if request.method == "POST":
        try:
            driver = driver_service.update_driver(driver_id, request.form.to_dict())
        except LookupError:
            abort(404)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("drivers.edit", driver_id=driver_id))
        flash(f"Driver {driver.name} updated", "success")
        return redirect(url_for("drivers.detail", driver_id=driver_id))
    form_data = {
        "name": driver.name,
        "phone": driver.phone or "",
        "license_number": driver.license_number or "",
        "card_code": driver.card_code,
        "status": driver.status,
        "card_status": driver.card_status,
        "notes": driver.notes or "",
    }
    return render_template(
        "drivers/form.html", form_data=form_data, mode="edit", driver=driver
    )


@bp.route("/<int:driver_id>/delete", methods=["POST"])
def delete(driver_id):
    try:
        driver_service.delete_driver(driver_id)
    except LookupError:
        abort(404)
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("drivers.list"))
    flash("Driver deleted", "success")
    return redirect(url_for("drivers.list"))
