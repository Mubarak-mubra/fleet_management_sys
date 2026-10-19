"""Account and session business logic.

Login failures are deliberately indistinguishable from one another: a wrong
password and an unknown username both return the same message, and both are
timing-comparable, so an attacker cannot enumerate accounts. Repeated failures
from one source are throttled to slow brute force.
"""
from datetime import datetime, timedelta

from werkzeug.security import check_password_hash

from extensions import db
from app.models import ROLES, User

from .parsing import parse_date  # noqa: F401  (re-exported for convenience)

# --- brute-force throttling ------------------------------------------------
# In-memory, per-process. Sufficient to blunt a single attacker against one
# worker; a multi-worker deployment should move this to the DB or Redis.
MAX_ATTEMPTS = 8
LOCKOUT_MINUTES = 15
_failed: dict[str, tuple[int, datetime]] = {}


def _source_key(source: str | None) -> str:
    return (source or "unknown").strip().lower()[:64]


def _is_locked(key: str) -> bool:
    record = _failed.get(key)
    if not record:
        return False
    count, last = record
    if count < MAX_ATTEMPTS:
        return False
    if datetime.now() - last > timedelta(minutes=LOCKOUT_MINUTES):
        _failed.pop(key, None)      # lockout expired; let them try again
        return False
    return True


def record_failure(key: str) -> None:
    count, _ = _failed.get(key, (0, datetime.now()))
    _failed[key] = (count + 1, datetime.now())


def clear_failures(key: str) -> None:
    _failed.pop(key, None)


def reset_throttle() -> None:
    """Test hook — clears all in-memory failure counters."""
    _failed.clear()


# --- lookups ---------------------------------------------------------------


def get_user(user_id: int) -> User:
    user = db.session.get(User, user_id)
    if user is None:
        raise LookupError(f"User {user_id} not found")
    return user


def find_by_username(username: str) -> User | None:
    username = str(username or "").strip()
    if not username:
        return None
    return User.query.filter(User.username.ilike(username)).first()


# --- authentication --------------------------------------------------------


def authenticate(username: str, password: str, source: str | None = None) -> User:
    """Return the logged-in user or raise ValueError.

    Always performs a password comparison — even for unknown usernames — so
    the response time does not reveal whether an account exists.
    """
    key = _source_key(source)

    if _is_locked(key):
        raise ValueError(f"Too many attempts. Try again in {LOCKOUT_MINUTES} minutes.")

    user = find_by_username(username)
    password = str(password or "")

    if user is None:
        # Dummy compare keeps timing flat for non-existent accounts.
        check_password_hash(
            "scrypt:32768:8:1$" + "x" * 160, "x" * max(len(password), 1)
        )
        record_failure(key)
        raise ValueError("Invalid username or password")

    if not user.check_password(password):
        record_failure(key)
        raise ValueError("Invalid username or password")

    if not user.active:
        record_failure(key)
        raise ValueError("This account is disabled. Contact an administrator.")

    clear_failures(key)
    user.last_login_at = datetime.now()
    db.session.commit()
    return user


# --- account management ----------------------------------------------------


def create_user(data: dict) -> User:
    username = str(data.get("username") or "").strip()
    if not username:
        raise ValueError("Username is required")
    if len(username) < 3:
        raise ValueError("Username must be at least 3 characters")
    if find_by_username(username) is not None:
        raise ValueError("That username is already taken")

    role = str(data.get("role") or "").strip() or "operator"
    if role not in ROLES:
        raise ValueError("Invalid role")

    user = User(
        username=username,
        display_name=str(data.get("display_name") or "").strip() or None,
        role=role,
    )
    user.set_password(data.get("password"))
    try:
        db.session.add(user)
        db.session.commit()
        return user
    except Exception:
        db.session.rollback()
        raise


def update_user(user_id: int, data: dict, *, actor: User | None = None) -> User:
    try:
        user = get_user(user_id)

        if "username" in data:
            username = str(data.get("username") or "").strip()
            if not username:
                raise ValueError("Username is required")
            existing = find_by_username(username)
            if existing is not None and existing.id != user.id:
                raise ValueError("That username is already taken")
            user.username = username

        if "display_name" in data:
            user.display_name = str(data.get("display_name") or "").strip() or None

        if "role" in data:
            role = str(data.get("role") or "").strip()
            if role not in ROLES:
                raise ValueError("Invalid role")
            # Never let the last admin demote themselves out of existence.
            if actor is not None and actor.id == user.id and role != "admin":
                raise ValueError("You cannot remove your own admin role")
            user.role = role

        if "active" in data:
            wants_active = str(data.get("active")).lower() in ("1", "true", "on", "yes")
            if not wants_active and actor is not None and actor.id == user.id:
                raise ValueError("You cannot disable your own account")
            if not wants_active and user.is_admin and _admin_count() <= 1:
                raise ValueError("At least one admin account must stay active")
            user.active = wants_active

        if str(data.get("password") or ""):
            user.set_password(data.get("password"))

        db.session.commit()
        return user
    except Exception:
        db.session.rollback()
        raise


def delete_user(user_id: int, *, actor: User | None = None) -> None:
    try:
        user = get_user(user_id)
        if actor is not None and actor.id == user.id:
            raise ValueError("You cannot delete your own account")
        if user.is_admin and _admin_count() <= 1:
            raise ValueError("At least one admin account must remain")
        db.session.delete(user)
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def _admin_count() -> int:
    return User.query.filter(User.role == "admin", User.active.is_(True)).count()


def list_users() -> list[User]:
    return User.query.order_by(User.role.asc(), User.username.asc()).all()


def count_users() -> int:
    return User.query.count()
