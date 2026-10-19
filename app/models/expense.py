from extensions import db

from .base import BaseModel

# Costs that are NOT fuel and NOT maintenance: insurance, registration, wages,
# parking, tolls, washing, fines, office overhead, etc. Fuel and maintenance
# keep their own specialised logs; this captures everything else.
EXPENSE_CATEGORIES = (
    "insurance",
    "registration",
    "wages",
    "parking",
    "toll",
    "washing",
    "fine",
    "office",
    "parts",
    "other",
)


class Expense(BaseModel):
    """A general fleet expense, optionally attributed to one vehicle.

    ``vehicle_id`` is nullable because some costs (office rent, fleet-wide
    insurance) belong to no single vehicle. On vehicle delete the link is
    nulled rather than cascading away the record — the money was still spent.
    """

    vehicle_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    expense_date = db.Column(db.Date, nullable=False, index=True)
    category = db.Column(
        db.Enum(*EXPENSE_CATEGORIES, name="expense_category"), default="other", index=True
    )
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    vendor = db.Column(db.String(120))
    payment_method = db.Column(db.String(40))
    receipt_ref = db.Column(db.String(80))
    notes = db.Column(db.Text)

    __table_args__ = (
        db.CheckConstraint("amount >= 0", name="ck_expense_amount"),
    )

    @property
    def vehicle_label(self) -> str:
        if self.vehicle is None:
            return "—"
        return self.vehicle.plate_number
