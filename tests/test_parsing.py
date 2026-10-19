from datetime import date, datetime

import pytest

from app.services.parsing import parse_date, parse_datetime, parse_float


class TestParseDate:
    def test_date_object_passthrough(self):
        d = date(2026, 10, 9)
        assert parse_date(d, "fuel_date") == d

    def test_datetime_coerced_to_date(self):
        assert parse_date(datetime(2026, 10, 9, 14, 30), "fuel_date") == date(2026, 10, 9)

    def test_iso_string(self):
        assert parse_date("2026-10-09", "fuel_date") == date(2026, 10, 9)

    def test_empty_string_returns_none(self):
        assert parse_date("", "fuel_date") is None

    def test_none_returns_none(self):
        assert parse_date(None, "fuel_date") is None

    def test_bad_format_raises(self):
        with pytest.raises(ValueError, match="Invalid fuel_date"):
            parse_date("09/10/2026", "fuel_date")

    def test_garbage_raises(self):
        with pytest.raises(ValueError, match="Invalid performed_date"):
            parse_date("not-a-date", "performed_date")


class TestParseDatetime:
    def test_datetime_local_format(self):
        assert parse_datetime("2026-10-09T14:30", "start_time") == datetime(2026, 10, 9, 14, 30)

    def test_space_format(self):
        assert parse_datetime("2026-10-09 14:30", "start_time") == datetime(2026, 10, 9, 14, 30)

    def test_datetime_object_naive(self):
        value = datetime(2026, 10, 9, 14, 30)
        assert parse_datetime(value, "start_time") == value

    def test_empty_string_returns_none(self):
        assert parse_datetime("", "end_time") is None

    def test_none_returns_none(self):
        assert parse_datetime(None, "end_time") is None

    def test_bad_format_raises(self):
        with pytest.raises(ValueError, match="Invalid start_time"):
            parse_datetime("tomorrow", "start_time")

    def test_partial_date_only_raises(self):
        with pytest.raises(ValueError, match="Invalid start_time"):
            parse_datetime("2026-10-09", "start_time")


class TestParseFloat:
    def test_numeric_string(self):
        assert parse_float("12.5", "liters") == 12.5

    def test_int_and_float_passthrough(self):
        assert parse_float(3, "cost") == 3.0
        assert parse_float(2.75, "cost") == 2.75

    def test_empty_returns_default(self):
        assert parse_float("", "odometer", default=0.0) == 0.0

    def test_none_returns_default(self):
        assert parse_float(None, "odometer") is None

    def test_empty_with_required_raises(self):
        with pytest.raises(ValueError, match="Invalid liters"):
            parse_float("", "liters", required=True)

    def test_none_with_required_raises(self):
        with pytest.raises(ValueError, match="Invalid liters"):
            parse_float(None, "liters", required=True)

    def test_bad_input_raises(self):
        with pytest.raises(ValueError, match="Invalid distance_km"):
            parse_float("far", "distance_km")
