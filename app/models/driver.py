from extensions import db

from .base import BaseModel

DRIVER_STATUSES = ("active", "inactive", "suspended")
CARD_STATUSES = ("active", "lost", "expired")


class Driver(BaseModel):
    """A registered driver and the fleet card issued to them.

    Trips reference a driver by id and also snapshot ``driver_name``, so trip
    history survives a driver being renamed or removed.
    """

    name = db.Column(db.String(120), nullable=False, index=True)
    phone = db.Column(db.String(30), nullable=True)
    license_number = db.Column(db.String(40), nullable=True)
    card_code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    card_status = db.Column(
        db.Enum(*CARD_STATUSES, name="driver_card_status"), default="active", index=True
    )
    status = db.Column(
        db.Enum(*DRIVER_STATUSES, name="driver_status"), default="active", index=True
    )
    notes = db.Column(db.Text, nullable=True)

    trips = db.relationship(
        "TripLog",
        backref=db.backref("driver", lazy="select"),
        lazy="select",
    )

    @property
    def is_available(self) -> bool:
        return self.status == "active" and self.card_status == "active"

    @property
    def trip_count(self) -> int:
        return len(self.trips)

    @property
    def open_trip_count(self) -> int:
        return len([t for t in self.trips if t.status in ("planned", "in_progress")])
