from extensions import db

from .base import BaseModel

PROJECT_STATUSES = ("planned", "active", "on_hold", "completed", "cancelled")


class Project(BaseModel):
    """A construction job/site that fleet work is reported against.

    Trips and expenses link to a project *optionally*: a trip genuinely goes
    to a site, and a site permit genuinely belongs to one. Office overhead
    and quick entries belong to no single job.

    Fuel and maintenance deliberately cannot link — a fill-up or a set of
    tyres serves whatever the vehicle does next, so nobody at the pump can
    name a project. Their project share is derived from trip distance
    instead (see project_service.project_cost_report).

    Both relationships deliberately do NOT cascade-delete — like expenses on
    a vehicle, the money was still spent, so deleting a project keeps the
    records and merely unlinks them (SQLAlchemy nulls the FK; the DB's
    ON DELETE SET NULL is the raw-SQL backstop, SQLite runs FKs off here).
    """

    name = db.Column(db.String(150), nullable=False, index=True)
    code = db.Column(db.String(30), unique=True, nullable=False, index=True)
    client = db.Column(db.String(150))
    location = db.Column(db.String(200))
    start_date = db.Column(db.Date, nullable=True)
    end_date = db.Column(db.Date, nullable=True)
    status = db.Column(
        db.Enum(*PROJECT_STATUSES, name="project_status"),
        default="planned",
        index=True,
    )
    notes = db.Column(db.Text)

    __table_args__ = (
        db.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="ck_project_dates",
        ),
    )

    trips = db.relationship(
        "TripLog",
        backref=db.backref("project", lazy="select"),
        lazy="select",
    )
    expenses = db.relationship(
        "Expense",
        backref=db.backref("project", lazy="select"),
        lazy="select",
    )

    @property
    def is_open(self) -> bool:
        return self.status in ("planned", "active", "on_hold")

    @property
    def label(self) -> str:
        """'PRJ-0001 — Ring Road Extension' for dropdowns and reports."""
        return f"{self.code} — {self.name}"
