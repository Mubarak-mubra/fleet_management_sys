from flask import Blueprint, render_template

bp = Blueprint("more", __name__)


@bp.route("/")
def index():
    """Overflow tab for the sections that don't fit the mobile tab bar.

    Maintenance and Drivers are real sections with their own blueprints; this
    page just links to them so the bottom nav stays at five comfortable tabs.
    """
    return render_template("more/index.html", mode="more")
