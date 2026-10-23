from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from extensions import db

from config import Config


def utcnow() -> datetime:
    """Naive UTC now. Used for audit stamps (created_at/updated_at) only —
    these are internal bookkeeping, never compared against user-entered times.

    Naive, tzinfo deliberately stripped: the whole schema stores naive UTC.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def local_now() -> datetime:
    """Naive 'now' on the company's own wall clock (see Config.APP_TIMEZONE).

    This is what user-facing defaults must use. Trip forms collect local
    wall-clock time from a dispatcher, so stamping a fallback in UTC puts it
    three hours behind the start_time it is about to be compared against —
    which is exactly why completing a trip that ended at 17:09 was rejected.
    """
    return datetime.now(ZoneInfo(Config.APP_TIMEZONE)).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class BaseModel(TimestampMixin, db.Model):
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
