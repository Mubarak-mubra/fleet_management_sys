from extensions import db

from .base import BaseModel

VEHICLE_TYPES = (
    "excavator",
    "dump_truck",
    "loader",
    "bulldozer",
    "crane",
    "concrete_mixer",
    "other",
)

VEHICLE_STATUSES = ("active", "maintenance", "inactive", "retired")


class Vehicle(BaseModel):
    name = db.Column(db.String(120), nullable=False)
    plate_number = db.Column(db.String(30), unique=True, nullable=False, index=True)
    vehicle_type = db.Column(
        db.Enum(*VEHICLE_TYPES, name="vehicle_type"), default="other"
    )
    make = db.Column(db.String(80))
    model = db.Column(db.String(80))
    year = db.Column(db.Integer)
    status = db.Column(
        db.Enum(*VEHICLE_STATUSES, name="vehicle_status"),
        default="active",
        index=True,
    )
    odometer = db.Column(db.Float, default=0)
    fuel_capacity_liters = db.Column(db.Float, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    trips = db.relationship(
        "TripLog",
        backref=db.backref("vehicle", lazy="select"),
        cascade="all, delete-orphan",
        lazy="select",
    )
    fuel_logs = db.relationship(
        "FuelLog",
        backref=db.backref("vehicle", lazy="select"),
        cascade="all, delete-orphan",
        lazy="select",
    )
    maintenance_logs = db.relationship(
        "MaintenanceLog",
        backref=db.backref("vehicle", lazy="select"),
        cascade="all, delete-orphan",
        lazy="select",
    )
    # Expenses deliberately do NOT cascade-delete: the money was spent, so the
    # record survives a vehicle being retired/removed. SQLAlchemy nulls the FK
    # itself (the DB's ON DELETE SET NULL is only a backstop for raw SQL, since
    # SQLite runs with foreign_keys OFF here).
    expenses = db.relationship(
        "Expense",
        backref=db.backref("vehicle", lazy="select"),
        lazy="select",
    )

    @property
    def is_available(self) -> bool:
        return self.status == "active"

    @property
    def total_fuel_liters(self) -> float:
        return float(sum(log.liters or 0 for log in self.fuel_logs))

    @property
    def total_maintenance_cost(self) -> float:
        return float(sum(log.cost or 0 for log in self.maintenance_logs))
