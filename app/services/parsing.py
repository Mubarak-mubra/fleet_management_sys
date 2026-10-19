"""Shared input coercion helpers. Must not import Flask."""
from datetime import date, datetime


def parse_date(value, field: str) -> date | None:
    """Accept date | datetime | "YYYY-MM-DD"; None/blank -> None; bad -> ValueError."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid {field}") from None


def parse_datetime(value, field: str) -> datetime | None:
    """Accept datetime | "YYYY-MM-DDTHH:MM" | "YYYY-MM-DD HH:MM"; naive; None/blank -> None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"Invalid {field}")


def parse_float(value, field: str, *, required: bool = False, default: float | None = None) -> float | None:
    """Accept int/float/numeric string; blank -> default (or ValueError when required)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise ValueError(f"Invalid {field}")
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {field}") from None
