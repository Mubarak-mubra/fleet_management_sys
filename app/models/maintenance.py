from datetime import date

from extensions import db

from .base import BaseModel

MAINTENANCE_TYPES = (
    "service",
    "repair",
    "inspection",
    "tire",
    "battery",
    "other",
)

MAINTENANCE_STATUSES = ("scheduled", "in_progress", "completed")


class MaintenanceLog(BaseModel):
    vehicle_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # No project here either. Tyres and services wear by distance and time,
    # spread across every job the vehicle works — not booked to one site.
    maintenance_type = db.Column(
        db.Enum(*MAINTENANCE_TYPES, name="maintenance_type"), default="service"
    )
    description = db.Column(db.String(255), nullable=False)
    performed_date = db.Column(db.Date, nullable=False)
    next_due_date = db.Column(db.Date, nullable=True)
    cost = db.Column(db.Float, default=0)
    odometer = db.Column(db.Float, nullable=True)
    vendor = db.Column(db.String(120))
    status = db.Column(
        db.Enum(*MAINTENANCE_STATUSES, name="maintenance_status"),
        default="completed",
    )
    notes = db.Column(db.Text)

    @property
    def is_overdue(self) -> bool:
        if self.next_due_date is None:
            return False
        return self.next_due_date < date.today() and self.status != "completed"
