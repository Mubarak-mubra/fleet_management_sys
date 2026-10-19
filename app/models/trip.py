from extensions import db

from .base import BaseModel

TRIP_STATUSES = ("planned", "in_progress", "completed", "cancelled")

# Display-only labels for trip status. The DB keeps the English enum values
# above — filtering, badge CSS classes and the API all depend on them — and
# these labels are applied at render time by the `trip_status` template filter.
TRIP_STATUS_LABELS = {
    "planned": "isku diyaarin bixit",
    "in_progress": "baxay",
    "completed": "dhameystiray",
    "cancelled": "lajoojiyay",
}


class TripLog(BaseModel):
    vehicle_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    driver_id = db.Column(
        db.Integer,
        db.ForeignKey("driver.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    driver_name = db.Column(db.String(120), nullable=False)
    purpose = db.Column(db.String(200), nullable=False)
    origin = db.Column(db.String(160), nullable=False)
    destination = db.Column(db.String(160), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=True)
    distance_km = db.Column(db.Float, default=0)
    odometer_start = db.Column(db.Float, nullable=True)
    odometer_end = db.Column(db.Float, nullable=True)
    status = db.Column(
        db.Enum(*TRIP_STATUSES, name="trip_status"), default="planned", index=True
    )
    notes = db.Column(db.Text)

    __table_args__ = (
        db.CheckConstraint(
            "end_time IS NULL OR end_time >= start_time", name="ck_trip_time"
        ),
    )

    @property
    def duration_hours(self) -> float | None:
        if self.start_time is None or self.end_time is None:
            return None
        return (self.end_time - self.start_time).total_seconds() / 3600

    @property
    def is_active(self) -> bool:
        return self.status in ("planned", "in_progress")
