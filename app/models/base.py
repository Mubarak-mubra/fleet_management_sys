from datetime import datetime, timezone

from extensions import db


def utcnow() -> datetime:
    """Naive UTC now — app-wide convention. tzinfo deliberately stripped."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TimestampMixin:
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )


class BaseModel(TimestampMixin, db.Model):
    __abstract__ = True

    id = db.Column(db.Integer, primary_key=True)
