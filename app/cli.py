from datetime import date, datetime

import click

from app.models import (
    Driver,
    Expense,
    FuelLog,
    MaintenanceLog,
    Project,
    TripLog,
    Vehicle,
    VehicleType,
)
from extensions import db

SEED_EPOCH = date(2026, 9, 1)


def register_commands(app):
    @app.cli.command("backup-db")
    @click.option("--out", "-o", default=None, help="Destination path (default: backups/vms-<timestamp>.db)")
    def backup_db():
        """Copy the SQLite database to a timestamped file.

        Uses SQLite's online backup API, so it is safe to run while the server
        is serving requests (a plain file copy could catch a half-written page).
        """
        import os
        import shutil
        import sqlite3
        from datetime import datetime as _dt

        uri = app.config.get("SQLALCHEMY_DATABASE_URI", "")
        if not uri.startswith("sqlite:///") or ":memory:" in uri:
            click.echo(f"Backup only supports SQLite files; got {uri!r}.", err=True)
            return 1

        src = uri.replace("sqlite:///", "", 1)
        if not os.path.exists(src):
            click.echo(f"Database file not found: {src}", err=True)
            return 1

        dest = out or os.path.join(
            "backups", f"vms-{_dt.now().strftime('%Y%m%d-%H%M%S')}.db"
        )
        parent = os.path.dirname(dest)
        if parent:
            os.makedirs(parent, exist_ok=True)

        try:
            source = sqlite3.connect(src)
            target = sqlite3.connect(dest)
            with target:
                source.backup(target)
            source.close()
            target.close()
        except sqlite3.Error as exc:
            click.echo(f"Backup failed: {exc}", err=True)
            return 1

        size = os.path.getsize(dest)
        click.echo(f"Backed up {src} -> {dest} ({size:,} bytes)")
        return 0

    @app.cli.command("create-user")
    @click.argument("username")
    @click.option("--role", type=click.Choice(["admin", "operator", "viewer"]),
                  default="admin", show_default=True)
    @click.option("--password", prompt=True, hide_input=True,
                  confirmation_prompt=True)
    @click.option("--display-name", default=None)
    def create_user(username, role, password, display_name):
        """Create an account from the command line (used for the first admin)."""
        from app.services import auth_service

        try:
            user = auth_service.create_user(
                {"username": username, "role": role, "password": password,
                 "display_name": display_name}
            )
        except ValueError as exc:
            click.echo(f"Error: {exc}", err=True)
            return 1
        click.echo(f"Created {user.username} (role={user.role}).")
        return 0

    @app.cli.command("seed-db")
    def seed_db():
        """Seed the database with deterministic demo fleet data."""
        existing = Vehicle.query.count()
        if existing > 0:
            click.echo(f"Database already seeded ({existing} vehicles). Nothing to do.")
            return 0

        try:
            _seed()
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

        click.echo(
            f"Seeded: {Project.query.count()} projects, {Driver.query.count()} drivers, "
            f"{VehicleType.query.count()} vehicle types, "
            f"{Vehicle.query.count()} vehicles, "
            f"{TripLog.query.count()} trips, {FuelLog.query.count()} fuel logs, "
            f"{MaintenanceLog.query.count()} maintenance logs, "
            f"{Expense.query.count()} expenses."
        )
        return 0

def _seed():
    """Lay down one coherent fleet story (see each helper's docstring).

    Three live jobs, five machines, five drivers. Trips and job costs are
    booked to the project they belong to; fuel and maintenance stay on the
    vehicle, which is how the real system works — a fill-up or a tyre serves
    whatever the vehicle does next, so it belongs to no single job.
    """
    drivers = _seed_drivers()
    projects = _seed_projects()
    _seed_vehicle_types()
    vehicles = _seed_vehicles()
    db.session.flush()

    db.session.add_all(_seed_trips(vehicles, drivers, projects))
    db.session.add_all(_seed_fuel(vehicles))
    db.session.add_all(_seed_maintenance(vehicles))
    db.session.add_all(_seed_expenses(vehicles, projects))


def _seed_projects():
    """Three construction jobs the whole dataset orbits."""
    rows = [
        Project(
            name="Jaziira Site Development", code="PRJ-0001",
            client="Jaziira Construction", location="Jaziira, Mogadishu",
            start_date=date(2026, 8, 15), status="active",
            notes="Earthworks contract — excavator GC-101 based on site; "
                  "dump truck GC-101 hauls spoil and fill sand.",
        ),
        Project(
            name="Howl-Wadaag Road Upgrade", code="PRJ-0002",
            client="Ministry of Roads", location="Howl-Wadaag",
            start_date=date(2026, 9, 1), end_date=date(2026, 12, 20),
            status="active",
            notes="Grading and aggregate surfacing — dozer GC-104 and loader "
                  "GC-103 on site, GC-102 delivers road base from the yard.",
        ),
        Project(
            name="Maka Al-Mukarama Drainage Works", code="PRJ-0003",
            client="Mogadishu Municipality", location="Maka Al-Mukarama",
            start_date=date(2026, 9, 15), end_date=date(2026, 11, 30),
            status="active",
            notes="Culverts and channel lining — concrete mixer GC-105 pours "
                  "on a fortnightly cycle.",
        ),
    ]
    db.session.add_all(rows)
    return {row.code: row for row in rows}


def _seed_drivers():
    """The fleet's five drivers, each issued a unique card."""
    specs = [
        # name, card, phone, license, status
        ("Abdi Ali", "DRV-0001", "+252 61 442 7715", "SO-DL-40219", "active"),
        ("Ahmed Omar", "DRV-0002", "+252 61 773 9082", "SO-DL-51874", "active"),
        ("Mohamed Hassan", "DRV-0003", "+252 63 450 6613", "SO-DL-33905", "active"),
        ("Farhan Yusuf", "DRV-0004", "+252 68 902 2748", "SO-DL-64120", "active"),
        ("Amina Warsame", "DRV-0005", "+252 63 337 5590", "SO-DL-77638", "active"),
    ]
    rows = [
        Driver(
            name=name, card_code=card, phone=phone,
            license_number=license_no, status=status,
            card_status="active",
        )
        for (name, card, phone, license_no, status) in specs
    ]
    db.session.add_all(rows)
    return {row.name: row for row in rows}


def _seed_vehicle_types():
    """Register the demo fleet's type vocabulary before the vehicles that
    use it — the Type dropdown and the delete guard read from this table."""
    existing = {t.name.lower() for t in VehicleType.query.all()}
    names = ("excavator", "dump_truck", "loader", "bulldozer", "concrete_mixer")
    rows = [VehicleType(name=name) for name in names if name not in existing]
    db.session.add_all(rows)
    return rows


def _seed_vehicles():
    """Five machines, one per project role; odometers are the values the
    seeded trips and fill-ups add up to (every reading below is consistent
    with these end-of-period figures)."""
    rows = [
        Vehicle(
            name="Excavator CAT-320", plate_number="GC-101",
            vehicle_type="excavator", status="active",
            make="Caterpillar", model="320", year=2020,
            odometer=16491.0, fuel_capacity_liters=240.0,
            notes="Primary earthmover — Jaziira Site (PRJ-0001)",
        ),
        Vehicle(
            name="Dump Truck Howo", plate_number="GC-102",
            vehicle_type="dump_truck", status="active",
            make="Sinotruk", model="HOWO 371", year=2019,
            odometer=98460.0, fuel_capacity_liters=300.0,
            notes="Hauls spoil to Jaziira and road base to Howl-Wadaag",
        ),
        Vehicle(
            name="Wheel Loader Komatsu", plate_number="GC-103",
            vehicle_type="loader", status="active",
            make="Komatsu", model="WA380", year=2018,
            odometer=41816.0, fuel_capacity_liters=260.0,
            notes="Loads trucks at Howl-Wadaag (PRJ-0002)",
        ),
        Vehicle(
            name="Bulldozer D6", plate_number="GC-104",
            vehicle_type="bulldozer", status="active",
            make="Caterpillar", model="D6", year=2016,
            odometer=27566.0, fuel_capacity_liters=280.0,
            notes="Grading at Howl-Wadaag (PRJ-0002)",
        ),
        Vehicle(
            name="Concrete Mixer", plate_number="GC-105",
            vehicle_type="concrete_mixer", status="active",
            make="Shacman", model="SX5255", year=2017,
            odometer=76056.0, fuel_capacity_liters=200.0,
            notes="Concrete pours — Maka Al-Mukarama (PRJ-0003)",
        ),
    ]
    db.session.add_all(rows)
    return {row.plate_number: row for row in rows}


def _seed_trips(vehicles, drivers, projects):
    """18 trips that tell the period's story.

    Odometer chains are exact: each trip starts where the vehicle's previous
    trip ended, so trip distances, fill-up readings and the vehicles'
    end-of-period odometers all agree. The one cancelled run never left the
    yard (no odometer), the in-progress haul is today's (2026-10-19), and two
    planned trips sit in the future.
    """
    def dt(month, day, hour, minute):
        return datetime(2026, month, day, hour, minute)

    J, H, M = "PRJ-0001", "PRJ-0002", "PRJ-0003"
    specs = [
        # vehicle, driver, purpose, origin, destination, start, end,
        # distance, odo_start, odo_end, status, project
        ("GC-102", "Abdi Ali", "Haul spoil to tip head", "Shibis Yard", "Jaziira Site",
         dt(9, 1, 6, 30), dt(9, 1, 9, 45), 42.5, 98000.0, 98042.5, "completed", J),
        ("GC-101", "Mohamed Hassan", "Mobilize excavator to site", "Shibis Yard", "Jaziira Site",
         dt(9, 2, 6, 0), dt(9, 2, 13, 0), 41.0, 16450.0, 16491.0, "completed", J),
        ("GC-102", "Ahmed Omar", "Deliver fill sand", "Balaad Sand Depot", "Jaziira Site",
         dt(9, 5, 7, 0), dt(9, 5, 10, 10), 38.0, 98042.5, 98080.5, "completed", J),
        ("GC-103", "Farhan Yusuf", "Mobilize wheel loader", "Shibis Yard", "Howl-Wadaag",
         dt(9, 8, 6, 15), dt(9, 8, 13, 30), 66.0, 41750.0, 41816.0, "completed", H),
        ("GC-102", "Abdi Ali", "Haul spoil to tip head", "Shibis Yard", "Jaziira Site",
         dt(9, 9, 6, 45), dt(9, 9, 10, 0), 42.5, 98080.5, 98123.0, "completed", J),
        ("GC-104", "Farhan Yusuf", "Mobilize dozer for grading", "Shibis Yard", "Howl-Wadaag",
         dt(9, 12, 6, 0), dt(9, 12, 14, 0), 66.0, 27500.0, 27566.0, "completed", H),
        ("GC-102", "Mohamed Hassan", "Deliver road base aggregate", "Shibis Yard", "Howl-Wadaag",
         dt(9, 14, 7, 15), dt(9, 14, 12, 0), 65.0, 98123.0, 98188.0, "completed", H),
        ("GC-105", "Amina Warsame", "Concrete pour — drainage culvert", "Shibis Yard", "Maka Al-Mukarama",
         dt(9, 18, 6, 45), dt(9, 18, 8, 30), 28.0, 76000.0, 76028.0, "completed", M),
        ("GC-102", "Ahmed Omar", "Fuel run to depot", "Shibis Yard", "Balaad Depot",
         dt(9, 18, 8, 0), None, None, None, None, "cancelled", None),
        ("GC-102", "Ahmed Omar", "Deliver aggregate", "Balaad Depot", "Howl-Wadaag",
         dt(9, 21, 7, 0), dt(9, 21, 11, 40), 61.0, 98188.0, 98249.0, "completed", H),
        ("GC-102", "Abdi Ali", "Haul spoil to tip head", "Shibis Yard", "Jaziira Site",
         dt(9, 26, 6, 30), dt(9, 26, 9, 45), 42.5, 98249.0, 98291.5, "completed", J),
        ("GC-102", "Mohamed Hassan", "Deliver road base aggregate", "Shibis Yard", "Howl-Wadaag",
         dt(10, 2, 7, 15), dt(10, 2, 12, 0), 65.0, 98291.5, 98356.5, "completed", H),
        ("GC-105", "Amina Warsame", "Concrete pour — channel lining", "Shibis Yard", "Maka Al-Mukarama",
         dt(10, 6, 6, 45), dt(10, 6, 8, 30), 28.0, 76028.0, 76056.0, "completed", M),
        ("GC-102", "Ahmed Omar", "Deliver aggregate", "Balaad Depot", "Howl-Wadaag",
         dt(10, 9, 7, 0), dt(10, 9, 11, 40), 61.0, 98356.5, 98417.5, "completed", H),
        ("GC-102", "Abdi Ali", "Haul spoil to tip head", "Shibis Yard", "Jaziira Site",
         dt(10, 16, 6, 30), dt(10, 16, 9, 45), 42.5, 98417.5, 98460.0, "completed", J),
        ("GC-102", "Ahmed Omar", "Haul spoil to tip head", "Shibis Yard", "Jaziira Site",
         dt(10, 19, 6, 30), None, 42.5, 98460.0, None, "in_progress", J),
        ("GC-105", "Amina Warsame", "Pour support — manhole bases", "Shibis Yard", "Maka Al-Mukarama",
         dt(10, 20, 6, 45), None, 28.0, None, None, "planned", M),
        ("GC-102", "Mohamed Hassan", "Deliver road base aggregate", "Shibis Yard", "Howl-Wadaag",
         dt(10, 23, 7, 15), None, 65.0, None, None, "planned", H),
    ]
    return [
        TripLog(
            vehicle=vehicles[plate], driver=drivers[driver], driver_name=driver,
            purpose=purpose, origin=origin, destination=dest,
            start_time=start, end_time=end,
            distance_km=dist, odometer_start=o0, odometer_end=o1,
            status=status,
            project=projects[code] if code else None,
        )
        for (plate, driver, purpose, origin, dest, start, end,
             dist, o0, o1, status, code) in specs
    ]


def _seed_fuel(vehicles):
    """16 fill-ups, coherent with the trip odometers above.

    The dump truck's readings advance with its hauls (fill-to-fill gives a
    plausible ~2.3 km/L for a loaded HOWO). Stationary machines keep a flat
    reading — they burn fuel working, not driving — and the mixer's site-tank
    draws carry no odometer at all, exactly like a bowser delivery where
    nobody notes the meter. That means only GC-102 produces a km/L figure,
    which is the honest answer for this fleet.

    No project is booked here, matching the real model: a fill-up serves
    whatever the vehicle does next, so project fuel is derived from trips
    instead (see project_service.project_cost_report).
    """
    site_note = "Drawn from site tank (bowser delivery)"
    specs = [
        # vehicle, date, liters, cost/L, odometer, supplier, receipt, notes
        ("GC-102", date(2026, 9, 2), 95.0, 1.14, 98042.5, "Hass Petroleum", "HP-77120", None),
        ("GC-101", date(2026, 9, 3), 300.0, 1.15, 16491.0, "Hass Petroleum", "HP-77135", site_note),
        ("GC-103", date(2026, 9, 8), 240.0, 1.12, 41816.0, "Al-Nur Fuel", "AN-30241", site_note),
        ("GC-104", date(2026, 9, 13), 260.0, 1.13, 27566.0, "Hass Petroleum", "HP-77402", site_note),
        ("GC-101", date(2026, 9, 17), 300.0, 1.14, 16491.0, "Shifa Petroleum", "SP-11876", site_note),
        ("GC-105", date(2026, 9, 19), 90.0, 1.20, None, "Somali Oil", "SO-56019", site_note),
        ("GC-103", date(2026, 9, 22), 240.0, 1.14, 41816.0, "Hass Petroleum", "HP-77518", site_note),
        ("GC-102", date(2026, 9, 26), 110.0, 1.16, 98291.5, "Shifa Petroleum", "SP-11955", None),
        ("GC-104", date(2026, 9, 27), 260.0, 1.15, 27566.0, "Somali Oil", "SO-56140", site_note),
        ("GC-101", date(2026, 10, 1), 300.0, 1.16, 16491.0, "Somali Oil", "SO-56203", site_note),
        ("GC-105", date(2026, 10, 5), 90.0, 1.22, None, "Al-Nur Fuel", "AN-30477", site_note),
        ("GC-103", date(2026, 10, 6), 240.0, 1.20, 41816.0, "Hass Petroleum", "HP-77790", site_note),
        ("GC-104", date(2026, 10, 11), 260.0, 1.21, 27566.0, "Shifa Petroleum", "SP-12104", site_note),
        ("GC-101", date(2026, 10, 15), 300.0, 1.18, 16491.0, "Al-Nur Fuel", "AN-30512", site_note),
        ("GC-102", date(2026, 10, 16), 75.0, 1.20, 98460.0, "Somali Oil", "SO-56355", None),
        ("GC-105", date(2026, 10, 17), 85.0, 1.19, None, "Hass Petroleum", "HP-77901", site_note),
    ]
    return [
        FuelLog(
            vehicle=vehicles[plate], fuel_date=day, liters=liters,
            cost_per_liter=cpl, odometer=odo, supplier=supplier,
            receipt_ref=receipt, notes=notes,
        )
        for (plate, day, liters, cpl, odo, supplier, receipt, notes) in specs
    ]


def _seed_maintenance(vehicles):
    """10 service records: 8 completed, the dozer's blade leak still in the
    shop queue (in_progress), and one overdue rear-axle inspection so the
    dashboard has something real to flag."""
    specs = [
        # vehicle, type, description, performed, next_due, cost, status, vendor, odometer
        ("GC-102", "tire", "Rear axle tire inspection", date(2026, 8, 20), date(2026, 10, 12),
         49.6, "scheduled", "Shibis Auto Workshop", 97950.0),
        ("GC-101", "service", "250-hour service", date(2026, 9, 5), date(2026, 12, 5),
         148.0, "completed", "Horn Auto Spares", 16491.0),
        ("GC-102", "repair", "Brake line replacement", date(2026, 9, 7), date(2027, 3, 7),
         102.0, "completed", "Banaadir Diesel", 98080.5),
        ("GC-104", "inspection", "Quarterly safety inspection", date(2026, 9, 11), date(2026, 12, 11),
         36.0, "completed", "Shibis Auto Workshop", 27500.0),
        ("GC-103", "tire", "Loader tire set replacement", date(2026, 9, 16), date(2027, 9, 16),
         336.0, "completed", "Horn Auto Spares", 41816.0),
        ("GC-103", "repair", "Boom hydraulic hose replacement", date(2026, 9, 24), None,
         185.0, "completed", "Banaadir Diesel", 41816.0),
        ("GC-104", "repair", "Dozer blade hydraulic leak", date(2026, 10, 1), date(2026, 11, 20),
         272.0, "in_progress", "Banaadir Diesel", 27566.0),
        ("GC-101", "service", "Hydraulic filter change", date(2026, 10, 3), date(2027, 1, 3),
         54.4, "completed", "Banaadir Diesel", 16491.0),
        ("GC-105", "repair", "Mixer drum paddle replacement", date(2026, 10, 8), None,
         160.0, "completed", "Shibis Auto Workshop", 76056.0),
        ("GC-102", "tire", "Rear axle tire rotation", date(2026, 10, 12), date(2027, 4, 12),
         49.6, "completed", "Shibis Auto Workshop", 98460.0),
    ]
    return [
        MaintenanceLog(
            vehicle=vehicles[plate], maintenance_type=mtype, description=description,
            performed_date=performed, next_due_date=next_due, cost=cost,
            status=status, vendor=vendor, odometer=odo,
        )
        for (plate, mtype, description, performed, next_due, cost, status,
             vendor, odo) in specs
    ]


def _seed_expenses(vehicles, projects):
    """12 bills: six fleet-wide (no vehicle, no project — rent, insurance,
    wages, registration) and six job-attributable costs (toll, fine, parts,
    permit) booked to the project that caused them."""
    J, H, M = "PRJ-0001", "PRJ-0002", "PRJ-0003"
    specs = [
        # vehicle, date, category, description, amount, vendor, payment, receipt, project
        (None, date(2026, 9, 1), "insurance", "Fleet insurance premium — Q4", 820.0,
         "Somali Insurance Group", "bank_transfer", "INV-2026-0901", None),
        (None, date(2026, 9, 1), "office", "Site office rent — September", 340.0,
         "Hodan Properties", "bank_transfer", "RENT-0926", None),
        (None, date(2026, 9, 15), "wages", "Driver wages — first half of September",
         1150.0, None, "mobile_money", None, None),
        (None, date(2026, 9, 20), "registration", "Annual fleet re-registration", 260.0,
         "Ministry of Transport", "bank_transfer", "REG-2026", None),
        ("GC-103", date(2026, 9, 12), "washing", "Loader wash-down before mobilization",
         22.0, "Shibis Auto Workshop", "cash", None, None),
        ("GC-102", date(2026, 9, 8), "toll", "Balaad road toll — sand run", 6.5,
         None, "cash", None, J),
        ("GC-104", date(2026, 9, 18), "fine", "Parking fine — Howl-Wadaag", 45.0,
         "Banaadir Municipality", "cash", "FINE-4471", H),
        ("GC-101", date(2026, 9, 24), "parts", "Replacement hydraulic hoses (non-service)",
         132.0, "Horn Auto Spares", "card", "RC-88120", J),
        (None, date(2026, 9, 30), "wages", "Driver wages — second half of September",
         1180.0, None, "mobile_money", None, None),
        (None, date(2026, 10, 1), "office", "Site office rent — October", 340.0,
         "Hodan Properties", "bank_transfer", "RENT-1026", None),
        ("GC-105", date(2026, 10, 4), "other", "Pour permit — Maka channel lining",
         60.0, "Mogadishu Municipality", "cash", "PERMIT-2210", M),
        ("GC-102", date(2026, 10, 10), "parts", "Air filter set", 78.0,
         "Horn Auto Spares", "card", "RC-88455", H),
    ]
    return [
        Expense(
            vehicle=vehicles[plate] if plate else None,
            expense_date=exp_date, category=category,
            description=description, amount=amount, vendor=vendor,
            payment_method=payment, receipt_ref=receipt,
            project=projects[code] if code else None,
        )
        for (plate, exp_date, category, description, amount, vendor,
             payment, receipt, code) in specs
    ]
