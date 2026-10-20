from datetime import date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.models import (
    MAINTENANCE_STATUSES,
    MAINTENANCE_TYPES,
    TRIP_STATUSES,
    VEHICLE_STATUSES,
    FuelLog,
    MaintenanceLog,
    TripLog,
    Vehicle,
)


def test_eight_tables_created(db):
    names = sorted(db.inspect(db.engine).get_table_names())
    assert names == [
        "driver", "expense", "fuel_log", "maintenance_log", "project", "trip_log", "user", "vehicle"
    ]


def test_fk_ondelete_cascade_in_ddl(db):
    for table in ("trip_log", "fuel_log", "maintenance_log"):
        rows = db.session.execute(text(f"PRAGMA foreign_key_list({table})")).fetchall()
        assert rows, f"no FKs on {table}"
        on_delete_values = [row[6] for row in rows]
        assert "CASCADE" in on_delete_values, (table, on_delete_values)


def test_orm_cascade_delete_wipes_children(db, make_vehicle, make_trip, make_fuel, make_maintenance):
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle)
    make_fuel(vehicle=vehicle)
    make_maintenance(vehicle=vehicle)
    assert TripLog.query.count() == 1
    assert FuelLog.query.count() == 1
    assert MaintenanceLog.query.count() == 1

    db.session.delete(vehicle)
    db.session.commit()

    assert Vehicle.query.count() == 0
    assert TripLog.query.count() == 0
    assert FuelLog.query.count() == 0
    assert MaintenanceLog.query.count() == 0


def test_ck_trip_time_rejects_end_before_start(db, make_vehicle):
    vehicle = make_vehicle()
    trip = TripLog(
        vehicle_id=vehicle.id,
        driver_name="A",
        purpose="p",
        origin="o",
        destination="d",
        start_time=datetime(2026, 2, 2, 10, 0),
        end_time=datetime(2026, 2, 2, 9, 0),
    )
    db.session.add(trip)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_ck_trip_time_allows_end_after_start(db, make_vehicle):
    vehicle = make_vehicle()
    trip = TripLog(
        vehicle_id=vehicle.id,
        driver_name="A",
        purpose="p",
        origin="o",
        destination="d",
        start_time=datetime(2026, 2, 2, 9, 0),
        end_time=datetime(2026, 2, 2, 10, 0),
    )
    db.session.add(trip)
    db.session.commit()
    assert TripLog.query.count() == 1


def test_ck_fuel_liters_rejects_zero(db, make_vehicle):
    vehicle = make_vehicle()
    log = FuelLog(vehicle_id=vehicle.id, fuel_date=date(2026, 3, 3), liters=0)
    db.session.add(log)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_ck_fuel_liters_rejects_negative(db, make_vehicle):
    vehicle = make_vehicle()
    log = FuelLog(vehicle_id=vehicle.id, fuel_date=date(2026, 3, 3), liters=-5)
    db.session.add(log)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_duplicate_plate_number_rejected(db):
    db.session.add(Vehicle(name="A", plate_number="GC-DUP"))
    db.session.commit()
    db.session.add(Vehicle(name="B", plate_number="GC-DUP"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_vehicle_not_nulls(db):
    db.session.add(Vehicle(plate_number="GC-NN1"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(Vehicle(name="No plate"))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_trip_not_nulls(db, make_vehicle):
    vehicle = make_vehicle()
    db.session.add(TripLog(vehicle_id=vehicle.id, purpose="p", origin="o", destination="d",
                           start_time=datetime(2026, 1, 1)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(TripLog(driver_name="d", purpose="p", origin="o", destination="d",
                           start_time=datetime(2026, 1, 1)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_fuel_and_maintenance_not_nulls(db, make_vehicle):
    vehicle = make_vehicle()
    db.session.add(FuelLog(vehicle_id=vehicle.id, liters=10))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()
    db.session.add(MaintenanceLog(vehicle_id=vehicle.id, performed_date=date(2026, 1, 1)))
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_property_is_available(make_vehicle):
    active = make_vehicle(status="active")
    maintenance = make_vehicle(status="maintenance")
    assert active.is_available is True
    assert maintenance.is_available is False


def test_property_total_fuel_liters_and_maintenance_cost(db, make_vehicle, make_fuel, make_maintenance):
    vehicle = make_vehicle()
    make_fuel(vehicle=vehicle, liters=40.0)
    make_fuel(vehicle=vehicle, liters=60.0)
    make_maintenance(vehicle=vehicle, cost=150.0)
    make_maintenance(vehicle=vehicle, cost=50.0)
    assert vehicle.total_fuel_liters == 100.0
    assert vehicle.total_maintenance_cost == 200.0


def test_property_duration_hours(make_trip):
    trip = make_trip(
        start_time=datetime(2026, 1, 1, 8, 0),
        end_time=datetime(2026, 1, 1, 11, 0),
    )
    assert trip.duration_hours == 3.0
    open_trip = make_trip()
    assert open_trip.duration_hours is None


def test_property_is_active(make_trip):
    planned = make_trip(status="planned")
    running = make_trip(status="in_progress")
    done = make_trip(status="completed")
    cancelled = make_trip(status="cancelled")
    assert planned.is_active is True
    assert running.is_active is True
    assert done.is_active is False
    assert cancelled.is_active is False


def test_property_computed_total(make_fuel):
    computed = make_fuel(liters=10.0, cost_per_liter=2.5, total_cost=None)
    explicit = make_fuel(liters=10.0, cost_per_liter=2.5, total_cost=99.0)
    zero_cost = make_fuel(liters=7.0, cost_per_liter=None, total_cost=None)
    assert computed.computed_total == 25.0
    assert explicit.computed_total == 99.0
    assert zero_cost.computed_total == 0.0


def test_property_is_overdue(make_maintenance):
    past_due = make_maintenance(next_due_date=date(2020, 1, 1), status="scheduled")
    future = make_maintenance(next_due_date=date(2999, 1, 1), status="scheduled")
    completed_past = make_maintenance(next_due_date=date(2020, 1, 1), status="completed")
    no_due = make_maintenance(next_due_date=None, status="scheduled")
    assert past_due.is_overdue is True
    assert future.is_overdue is False
    assert completed_past.is_overdue is False
    assert no_due.is_overdue is False


def test_enum_tuples_exported_and_match_spec():
    assert VEHICLE_STATUSES == ("active", "maintenance", "inactive", "retired")
    assert TRIP_STATUSES == ("planned", "in_progress", "completed", "cancelled")
    assert MAINTENANCE_TYPES == ("service", "repair", "inspection", "tire", "battery", "other")
    assert MAINTENANCE_STATUSES == ("scheduled", "in_progress", "completed")
