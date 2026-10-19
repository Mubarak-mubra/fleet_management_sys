from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db

from .base import BaseModel

# admin    - everything, including managing user accounts
# operator - day-to-day record keeping (create/edit/delete fleet records)
# viewer   - read-only; cannot POST at all
ROLES = ("admin", "operator", "viewer")
DEFAULT_ROLE = "operator"


class User(BaseModel):
    """An account that can log in.

    Passwords are never stored in plaintext: Werkzeug hashes them with scrypt
    (its current default), which is deliberately slow to thwart brute force.
    ``last_login_at`` is informational only — it is not a security control.
    """

    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.Enum(*ROLES, name="user_role"), default=DEFAULT_ROLE, index=True)
    active = db.Column(db.Boolean, default=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=True)
    last_login_at = db.Column(db.DateTime, nullable=True)

    def set_password(self, password: str) -> None:
        """Hash and store. Raises ValueError on a weak/blank password."""
        password = str(password or "")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        """Constant-ish time check; never raises on a bad hash."""
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, str(password or ""))

    # -- authorisation -----------------------------------------------------

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def can_write(self) -> bool:
        """Viewers are read-only; admins and operators may mutate records."""
        return self.role in ("admin", "operator") and bool(self.active)

    @property
    def role_label(self) -> str:
        return self.role.replace("_", " ").title() if self.role else ""

    @property
    def is_anonymous(self) -> bool:
        return False
