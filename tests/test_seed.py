from collections import Counter
from datetime import datetime, date

from app.models import Driver, Expense, FuelLog, MaintenanceLog, Project, TripLog, Vehicle, VehicleType
from app.services import fuel_service, maintenance_service


def run_seed(app):
    return app.test_cli_runner().invoke(args=["seed-db"])


def test_seed_db_exit_code_and_summary(app):
    result = run_seed(app)
    assert result.exit_code == 0, result.output
    assert (
        "Seeded: 3 projects, 5 drivers, 5 vehicle types, 5 vehicles, "
        "18 trips, 16 fuel logs, 10 maintenance logs, 12 expenses." in result.output
    )


def test_seed_creates_expected_counts(app):
    run_seed(app)
    assert Driver.query.count() == 5
    assert Vehicle.query.count() == 5
    assert VehicleType.query.count() == 5
    assert Project.query.count() == 3
    assert TripLog.query.count() == 18
    assert FuelLog.query.count() == 16
    assert MaintenanceLog.query.count() == 10
    assert Expense.query.count() == 12


def test_seed_projects_exist_with_codes(app):
    run_seed(app)
    codes = sorted(p.code for p in Project.query.all())
    assert codes == ["PRJ-0001", "PRJ-0002", "PRJ-0003"]
    howl = Project.query.filter_by(code="PRJ-0002").one()
    assert howl.status == "active"
    assert howl.end_date == date(2026, 12, 20)


def test_seed_links_trips_and_expenses_to_projects(app):
    """Trips and expenses carry a project; fuel and maintenance never do."""
    run_seed(app)
    jaziira = Project.query.filter_by(code="PRJ-0001").one()
    howl = Project.query.filter_by(code="PRJ-0002").one()
    maka = Project.query.filter_by(code="PRJ-0003").one()

    # Trips: 7 / 7 / 3 per project, plus the cancelled yard run unassigned.
    assert TripLog.query.filter_by(project_id=jaziira.id).count() == 7
    assert TripLog.query.filter_by(project_id=howl.id).count() == 7
    assert TripLog.query.filter_by(project_id=maka.id).count() == 3
    assert TripLog.query.filter_by(project_id=None).count() == 1

    # Fuel and maintenance belong to a vehicle and to no project at all —
    # there is no project column to filter on, which is the point.
    assert not hasattr(FuelLog, "project_id")
    assert not hasattr(MaintenanceLog, "project_id")
    # Every fill-up and service is still pinned to a real vehicle.
    assert FuelLog.query.filter_by(vehicle_id=None).count() == 0
    assert MaintenanceLog.query.filter_by(vehicle_id=None).count() == 0

    # Expenses: six fleet-wide bills plus the wash-down have no project;
    # the toll, fine, hoses, permit and filters are booked to a job.
    assert Expense.query.filter_by(project_id=None).count() == 7
    assert Expense.query.filter(Expense.project_id.isnot(None)).count() == 5


def test_seed_is_idempotent(app):
    first = run_seed(app)
    assert first.exit_code == 0, first.output

    second = run_seed(app)
    assert second.exit_code == 0, second.output
    assert "Database already seeded (5 vehicles). Nothing to do." in second.output

    assert Project.query.count() == 3
    assert TripLog.query.count() == 18
    assert FuelLog.query.count() == 16


def test_seed_deterministic_values(app):
    run_seed(app)

    gc101 = Vehicle.query.filter_by(plate_number="GC-101").first()
    assert gc101 is not None
    assert gc101.name == "Excavator CAT-320"
    assert gc101.status == "active"
    # End-of-period odometer equals what the seeded trip chain adds up to.
    assert gc101.odometer == 16491.0

    plates = [v.plate_number for v in Vehicle.query.all()]
    assert sorted(plates) == ["GC-101", "GC-102", "GC-103", "GC-104", "GC-105"]
    assert all(v.status == "active" for v in Vehicle.query.all())


def test_seed_exactly_one_overdue_maintenance(app):
    run_seed(app)
    overdue = maintenance_service.overdue_items()
    assert len(overdue) == 1
    assert overdue[0].next_due_date == date(2026, 10, 12)
    assert overdue[0].description == "Rear axle tire inspection"


def test_seed_trip_status_distribution(app):
    run_seed(app)
    dist = Counter(t.status for t in TripLog.query.all())
    assert dist == Counter(
        {"completed": 14, "planned": 2, "in_progress": 1, "cancelled": 1}
    )


def test_seed_maintenance_status_distribution(app):
    run_seed(app)
    dist = Counter(m.status for m in MaintenanceLog.query.all())
    assert dist == Counter({"completed": 8, "scheduled": 1, "in_progress": 1})


def test_seed_is_clock_independent(app):
    run_seed(app)
    trip = TripLog.query.filter_by(driver_name="Abdi Ali", status="completed").first()
    assert trip.start_time == datetime(2026, 9, 1, 6, 30)
    assert trip.end_time == datetime(2026, 9, 1, 9, 45)
    assert trip.distance_km == 42.5


def test_seed_odometer_chains_are_consistent(app):
    """Each trip starts where the vehicle's previous trip ended, and the
    vehicle's stored odometer equals the end of the last finished trip."""
    run_seed(app)
    for vehicle in Vehicle.query.all():
        trips = [
            t
            for t in TripLog.query.filter_by(vehicle_id=vehicle.id).all()
            if t.odometer_start is not None
        ]
        trips.sort(key=lambda t: t.start_time)
        for prev, curr in zip(trips, trips[1:]):
            if curr.odometer_start is None:
                continue
            assert curr.odometer_start >= prev.odometer_end, (
                f"{vehicle.plate_number}: {curr.start_time} starts at "
                f"{curr.odometer_start} before previous end {prev.odometer_end}"
            )
        finished = [t for t in trips if t.odometer_end is not None]
        if finished:
            assert vehicle.odometer >= max(t.odometer_end for t in finished)


def test_seed_fuel_efficiency_is_sane(app):
    """Only the moving truck produces a km/L figure, and it lands in the
    range a loaded HOWO actually runs (~2.3 km/L)."""
    run_seed(app)
    stats = fuel_service.fuel_efficiency()
    assert stats["interval_count"] == 2
    assert stats["by_vehicle"].keys() == {
        Vehicle.query.filter_by(plate_number="GC-102").one().id
    }
    assert 2.0 < stats["avg_km_per_liter"] < 2.6


def test_seed_trip_distance_matches_odometer_delta(app):
    run_seed(app)
    for trip in TripLog.query.filter_by(status="completed").all():
        if trip.odometer_start is not None and trip.odometer_end is not None:
            assert trip.distance_km == trip.odometer_end - trip.odometer_start
