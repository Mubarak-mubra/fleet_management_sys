from extensions import db

from .base import BaseModel


class FuelLog(BaseModel):
    vehicle_id = db.Column(
        db.Integer,
        db.ForeignKey("vehicle.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = db.Column(
        db.Integer,
        db.ForeignKey("project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    fuel_date = db.Column(db.Date, nullable=False, index=True)
    liters = db.Column(db.Float, nullable=False)
    cost_per_liter = db.Column(db.Float, nullable=True)
    total_cost = db.Column(db.Float, nullable=True)
    supplier = db.Column(db.String(120))
    odometer = db.Column(db.Float, nullable=True)
    receipt_ref = db.Column(db.String(80))
    notes = db.Column(db.Text)

    __table_args__ = (
        db.CheckConstraint("liters > 0", name="ck_fuel_liters"),
    )

    @property
    def computed_total(self) -> float:
        if self.total_cost is not None:
            return float(self.total_cost)
        return float(self.liters * (self.cost_per_liter or 0))
