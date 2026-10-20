import uuid
from datetime import date, datetime

import pytest

from app import create_app
from app.models import (
    Driver,
    Expense,
    FuelLog,
    MaintenanceLog,
    Project,
    TripLog,
    User,
    Vehicle,
    VehicleType,
)
from extensions import db as _db


@pytest.fixture()
def make_user(db):
    def _make(**overrides):
        data = dict(
            username=f"u{uuid.uuid4().hex[:10]}",
            role="admin",
            active=True,
            display_name="Test User",
        )
        password = overrides.pop("password", "secretpass123")
        data.update(overrides)
        user = User(**data)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return user

    return _make


@pytest.fixture()
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture()
def client(app, make_user):
    """A client already signed in as an admin.

    Authentication stays ENABLED in tests — the guards under test are the real
    ones. Only CSRF is relaxed (see TestConfig). Use `anon_client` to probe
    the unauthenticated paths.
    """
    user = make_user(username="admin", role="admin")
    c = app.test_client()
    with app.app_context():
        c.post(
            "/auth/login",
            data={"username": user.username, "password": "secretpass123"},
        )
    return c


@pytest.fixture()
def anon_client(app):
    """A client with no session — for asserting redirects to login."""
    return app.test_client()


@pytest.fixture()
def viewer_client(app, make_user):
    """A signed-in read-only user; every POST must be refused with 403."""
    user = make_user(username="viewer1", role="viewer")
    c = app.test_client()
    with app.app_context():
        c.post(
            "/auth/login",
            data={"username": user.username, "password": "secretpass123"},
        )
    return c


@pytest.fixture()
def db(app):
    return _db


@pytest.fixture()
def make_vehicle_type(db):
    def _make(name="Excavator"):
        vehicle_type = VehicleType(name=name)
        db.session.add(vehicle_type)
        db.session.commit()
        return vehicle_type

    return _make


@pytest.fixture()
def make_vehicle(db):
    def _make(**overrides):
        data = dict(
            name="Test Vehicle",
            plate_number=f"GC-{uuid.uuid4().hex[:8].upper()}",
            vehicle_type="excavator",
            status="active",
            year=2020,
            odometer=1000.0,
        )
        data.update(overrides)
        vehicle = Vehicle(**data)
        db.session.add(vehicle)
        db.session.commit()
        return vehicle

    return _make


@pytest.fixture()
def make_driver(db):
    def _make(**overrides):
        data = dict(
            name="Test Driver",
            card_code=f"DRV-{uuid.uuid4().hex[:8].upper()}",
            phone="+1 555 010 2030",
            license_number="DL-12345",
            status="active",
            card_status="active",
        )
        data.update(overrides)
        driver = Driver(**data)
        db.session.add(driver)
        db.session.commit()
        return driver

    return _make


@pytest.fixture()
def make_project(db):
    def _make(**overrides):
        data = dict(
            name="Test Project",
            code=f"PRJ-{uuid.uuid4().hex[:8].upper()}",
            status="active",
        )
        data.update(overrides)
        project = Project(**data)
        db.session.add(project)
        db.session.commit()
        return project

    return _make


@pytest.fixture()
def make_expense(db, make_vehicle):
    def _make(vehicle=None, **overrides):
        data = dict(
            vehicle_id=vehicle.id if vehicle is not None else None,
            expense_date=date(2026, 9, 1),
            category="other",
            description="Test expense",
            amount=100.0,
        )
        data.update(overrides)
        expense = Expense(**data)
        db.session.add(expense)
        db.session.commit()
        return expense

    return _make


@pytest.fixture()
def make_trip(db, make_vehicle):
    def _make(vehicle=None, **overrides):
        if vehicle is None:
            vehicle = make_vehicle()
        data = dict(
            vehicle_id=vehicle.id,
            driver_name="Test Driver",
            purpose="Test purpose",
            origin="Yard",
            destination="Site A",
            start_time=datetime(2026, 1, 1, 8, 0),
            status="planned",
        )
        data.update(overrides)
        trip = TripLog(**data)
        db.session.add(trip)
        db.session.commit()
        return trip

    return _make


@pytest.fixture()
def make_fuel(db, make_vehicle):
    def _make(vehicle=None, **overrides):
        if vehicle is None:
            vehicle = make_vehicle()
        data = dict(
            vehicle_id=vehicle.id,
            fuel_date=date(2026, 1, 10),
            liters=50.0,
            cost_per_liter=1.5,
        )
        data.update(overrides)
        log = FuelLog(**data)
        db.session.add(log)
        db.session.commit()
        return log

    return _make


@pytest.fixture()
def make_maintenance(db, make_vehicle):
    def _make(vehicle=None, **overrides):
        if vehicle is None:
            vehicle = make_vehicle()
        data = dict(
            vehicle_id=vehicle.id,
            maintenance_type="service",
            description="Routine service",
            performed_date=date(2026, 1, 5),
            cost=100.0,
            status="completed",
        )
        data.update(overrides)
        log = MaintenanceLog(**data)
        db.session.add(log)
        db.session.commit()
        return log

    return _make
