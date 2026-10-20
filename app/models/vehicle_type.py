from extensions import db

from .base import BaseModel


class VehicleType(BaseModel):
    """A fleet's own vocabulary of machine types ("Tipper", "Grader"...).

    Managed on the Vehicles -> Vehicle Types subtab; the vehicle form's
    Type dropdown is built from these rows — nothing is hardcoded. Vehicles
    store the registered name as text, and the delete route blocks removal
    while vehicles still reference the type.
    """

    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
