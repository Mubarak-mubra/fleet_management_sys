import re
from datetime import date, datetime, timedelta

from app.models import Vehicle
from app.services import trip_service


def seed(app):
    result = app.test_cli_runner().invoke(args=["seed-db"])
    assert result.exit_code == 0, result.output


def kpi_card(body, label):
    """Return the value shown on the KPI card whose label is ``label``.

    The card renders icon, then value, then label, then a sub-line, so the
    value has to be pulled from the same ``kpi-body`` block rather than from
    whatever happens to precede the label in the document.
    """
    block = re.search(
        rf'<span class="kpi-body">\s*<span class="kpi-value">([^<]+)</span>'
        rf'\s*<span class="kpi-label">{re.escape(label)}</span>',
        body,
    )
    assert block, f"KPI '{label}' not found in body"
    return block.group(1).strip()


def test_dashboard_empty_db_returns_200(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Total cars" in body
    assert "No trips yet." in body
    assert "No fuel logs yet." in body


def test_dashboard_shows_exactly_four_kpis(client):
    """Operational counts only — money lives on its own pages now."""
    body = client.get("/").get_data(as_text=True)
    cards = re.findall(r'class="kpi-card kpi-card--(\w+)"', body)
    assert cards == ["fleet", "ok", "warn", "info"], cards
    for label in ("Total cars", "Available", "Under maintenance", "Trips today"):
        assert f'<span class="kpi-label">{label}</span>' in body, label


def test_dashboard_kpis_match_database(app, client):
    seed(app)
    body = client.get("/").get_data(as_text=True)

    assert kpi_card(body, "Total cars") == str(Vehicle.query.count())
    assert kpi_card(body, "Available") == str(
        Vehicle.query.filter(Vehicle.status == "active").count()
    )
    assert kpi_card(body, "Under maintenance") == str(
        Vehicle.query.filter(Vehicle.status == "maintenance").count()
    )
    assert kpi_card(body, "Trips today") == str(trip_service.trips_active_on())


def test_dashboard_kpi_links_reach_the_filtered_lists(client):
    """Each card drills into the list it summarizes."""
    body = client.get("/").get_data(as_text=True)
    assert 'href="/vehicles/"' in body
    assert 'href="/vehicles/?status=active"' in body
    assert 'href="/vehicles/?status=maintenance"' in body
    assert 'href="/trips/"' in body


def test_dashboard_seeded_content(app, client):
    seed(app)
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "GC-101" in body


def test_dashboard_moved_money_off_the_dashboard(app, client):
    """Cost totals no longer sit on the dashboard; they belong to their pages.

    Guards the decision to keep the KPI row purely operational, so a future
    edit cannot quietly re-introduce a money card.
    """
    body = client.get("/").get_data(as_text=True)
    for money_label in ("Fuel cost", "Maintenance cost", "Other expenses", "Fuel this period"):
        assert money_label not in body, f"{money_label} crept back onto the dashboard"


# ---- trips_active_on -------------------------------------------------------

def test_trips_active_on_counts_running_trips(app, make_trip):
    make_trip(start_time=datetime(2020, 1, 1, 8, 0), status="in_progress")
    with app.app_context():
        assert trip_service.trips_active_on() == 1


def test_trips_active_on_excludes_cancelled(app, make_trip):
    """A cancelled trip leaves the board for every day, not just its own."""
    make_trip(
        start_time=datetime.combine(date.today(), datetime.min.time()),
        status="cancelled",
    )
    with app.app_context():
        assert trip_service.trips_active_on() == 0


def test_trips_active_on_excludes_future_trips(app, make_trip):
    make_trip(start_time=datetime(2099, 1, 1, 9, 0), status="planned")
    with app.app_context():
        assert trip_service.trips_active_on() == 0


def test_trips_active_on_counts_a_trip_that_already_finished_today(app, make_trip):
    """Ending today still counts as today — the trip did run."""
    today = date.today()
    make_trip(
        start_time=datetime.combine(today, datetime.min.time()),
        end_time=datetime.combine(today, datetime.min.time().replace(hour=17)),
        status="completed",
    )
    with app.app_context():
        assert trip_service.trips_active_on() == 1


def test_trips_active_on_counts_a_trip_spanning_midnight(app, make_trip):
    """Started yesterday evening, ends in the early hours: out today too."""
    yesterday = date.today() - timedelta(days=1)
    make_trip(
        start_time=datetime.combine(yesterday, datetime.min.time().replace(hour=22)),
        end_time=datetime.combine(date.today(), datetime.min.time().replace(hour=2)),
        status="completed",
    )
    with app.app_context():
        assert trip_service.trips_active_on() == 1


def test_trips_active_on_excludes_a_trip_that_finished_yesterday(app, make_trip):
    yesterday = date.today() - timedelta(days=1)
    make_trip(
        start_time=datetime.combine(yesterday, datetime.min.time().replace(hour=8)),
        end_time=datetime.combine(yesterday, datetime.min.time().replace(hour=17)),
        status="completed",
    )
    with app.app_context():
        assert trip_service.trips_active_on() == 0


def test_sidebar_dashboard_link_resolves(client):
    body = client.get("/").get_data(as_text=True)
    assert 'href="/"' in body
