from datetime import datetime

import pytest

from app.models import TripLog
from app.services import trip_service


class TestListTrips:
    def test_empty(self, db):
        assert trip_service.list_trips() == ([], 0, 1)

    def test_vehicle_filter(self, make_vehicle, make_trip):
        v1 = make_vehicle()
        v2 = make_vehicle()
        make_trip(vehicle=v1)
        make_trip(vehicle=v2)
        items, total, _ = trip_service.list_trips(vehicle_id=v1.id)
        assert total == 1
        assert items[0].vehicle_id == v1.id

    def test_status_filter(self, make_trip):
        make_trip(status="planned")
        make_trip(status="completed")
        items, total, _ = trip_service.list_trips(status="completed")
        assert total == 1
        assert items[0].status == "completed"

    def test_order_start_time_desc(self, make_vehicle, make_trip):
        vehicle = make_vehicle()
        make_trip(vehicle=vehicle, start_time=datetime(2026, 1, 1))
        make_trip(vehicle=vehicle, start_time=datetime(2026, 6, 1))
        make_trip(vehicle=vehicle, start_time=datetime(2026, 3, 1))
        items, _, _ = trip_service.list_trips()
        dates = [t.start_time for t in items]
        assert dates == sorted(dates, reverse=True)


class TestGetTrip:
    def test_returns_trip(self, make_trip):
        trip = make_trip()
        assert trip_service.get_trip(trip.id).id == trip.id

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.get_trip(999)


class TestCreateTrip:
    def test_valid_planned(self, db, make_vehicle):
        vehicle = make_vehicle()
        trip = trip_service.create_trip({
            "vehicle_id": str(vehicle.id),
            "driver_name": "Abdi Ali",
            "purpose": "Haul soil",
            "origin": "Yard",
            "destination": "Site A",
            "start_time": "2026-10-09T08:00",
        })
        assert trip.status == "planned"
        assert db.session.get(TripLog, trip.id) is not None

    def test_valid_in_progress_status_allowed(self, make_vehicle):
        vehicle = make_vehicle()
        trip = trip_service.create_trip({
            "vehicle_id": vehicle.id,
            "driver_name": "Abdi Ali",
            "purpose": "Haul",
            "origin": "Yard",
            "destination": "Site A",
            "start_time": "2026-10-09T08:00",
            "status": "in_progress",
        })
        assert trip.status == "in_progress"

    def test_rule6_missing_vehicle_id(self, app):
        with pytest.raises(ValueError, match="Vehicle not found"):
            trip_service.create_trip({
                "driver_name": "A", "purpose": "p", "origin": "o",
                "destination": "d", "start_time": "2026-10-09T08:00",
            })

    def test_rule6_unresolvable_vehicle_id(self, app):
        with pytest.raises(ValueError, match="Vehicle not found"):
            trip_service.create_trip({
                "vehicle_id": 999,
                "driver_name": "A", "purpose": "p", "origin": "o",
                "destination": "d", "start_time": "2026-10-09T08:00",
            })

    @pytest.mark.parametrize("field,label", [
        ("driver_name", "Driver name"),
        ("purpose", "Purpose"),
        ("origin", "Origin"),
        ("destination", "Destination"),
    ])
    def test_rule7_required_fields(self, make_vehicle, field, label):
        vehicle = make_vehicle()
        data = {
            "vehicle_id": vehicle.id,
            "driver_name": "A", "purpose": "p", "origin": "o",
            "destination": "d", "start_time": "2026-10-09T08:00",
        }
        data[field] = "  "
        with pytest.raises(ValueError, match=f"{label} is required"):
            trip_service.create_trip(data)

    def test_rule7_missing_start_time(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Start time is required"):
            trip_service.create_trip({
                "vehicle_id": vehicle.id,
                "driver_name": "A", "purpose": "p", "origin": "o", "destination": "d",
            })

    def test_rule8_end_before_start(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            trip_service.create_trip({
                "vehicle_id": vehicle.id,
                "driver_name": "A", "purpose": "p", "origin": "o", "destination": "d",
                "start_time": "2026-10-09T10:00",
                "end_time": "2026-10-09T09:00",
            })

    def test_rule8_end_after_start_ok(self, make_vehicle):
        vehicle = make_vehicle()
        trip = trip_service.create_trip({
            "vehicle_id": vehicle.id,
            "driver_name": "A", "purpose": "p", "origin": "o", "destination": "d",
            "start_time": "2026-10-09T08:00",
            "end_time": "2026-10-09T09:00",
        })
        assert trip.end_time == datetime(2026, 10, 9, 9, 0)

    def test_rule9_bad_create_status(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Invalid trip status"):
            trip_service.create_trip({
                "vehicle_id": vehicle.id,
                "driver_name": "A", "purpose": "p", "origin": "o", "destination": "d",
                "start_time": "2026-10-09T08:00",
                "status": "completed",
            })


class TestUpdateTrip:
    def test_updates_fields(self, make_trip):
        trip = make_trip()
        updated = trip_service.update_trip(trip.id, {"driver_name": "Ama Mensah", "purpose": "Crane lift"})
        assert updated.driver_name == "Ama Mensah"
        assert updated.purpose == "Crane lift"

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.update_trip(999, {"driver_name": "x"})

    def test_rule9_status_must_be_valid_enum(self, make_trip):
        trip = make_trip()
        with pytest.raises(ValueError, match="Invalid trip status"):
            trip_service.update_trip(trip.id, {"status": "teleporting"})

    def test_rule8_end_before_start_on_update(self, make_trip):
        trip = make_trip(start_time=datetime(2026, 5, 5, 10, 0))
        with pytest.raises(ValueError, match="end_time must be after start_time"):
            trip_service.update_trip(trip.id, {"end_time": "2026-05-05T09:00"})


class TestStartTrip:
    def test_from_planned(self, db, make_trip):
        trip = make_trip(status="planned")
        started = trip_service.start_trip(trip.id)
        assert started.status == "in_progress"
        assert started.start_time is not None

    def test_keeps_existing_start_time(self, make_trip):
        original = datetime(2026, 4, 4, 7, 30)
        trip = make_trip(status="planned", start_time=original)
        started = trip_service.start_trip(trip.id)
        assert started.start_time == original

    def test_rule10_twice_rejected(self, make_trip):
        trip = make_trip(status="planned")
        trip_service.start_trip(trip.id)
        with pytest.raises(ValueError, match="Only planned trips can be started"):
            trip_service.start_trip(trip.id)
        assert db_status(trip) == "in_progress"

    def test_rule10_from_completed_rejected(self, make_trip):
        trip = make_trip(status="completed")
        with pytest.raises(ValueError, match="Only planned trips can be started"):
            trip_service.start_trip(trip.id)

    def test_rule10_from_cancelled_rejected(self, make_trip):
        trip = make_trip(status="cancelled")
        with pytest.raises(ValueError, match="Only planned trips can be started"):
            trip_service.start_trip(trip.id)

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.start_trip(999)


def db_status(trip):
    from extensions import db

    return db.session.get(TripLog, trip.id).status


class TestCompleteTrip:
    def test_from_in_progress(self, make_trip):
        trip = make_trip(status="in_progress")
        completed = trip_service.complete_trip(trip.id)
        assert completed.status == "completed"
        assert completed.end_time is not None

    def test_keeps_end_time_already_on_the_trip(self, make_trip):
        """The Complete button submits no fields, so an end time the dispatcher
        already entered must survive — not be discarded for a fresh 'now'.

        The trip here is dated after any real clock, which is what made the
        bug bite: the fallback 'now' landed before start_time and the trip
        could never be completed at all.
        """
        start = datetime(2099, 6, 1, 16, 4)
        recorded_end = datetime(2099, 6, 1, 17, 9)
        trip = make_trip(status="in_progress", start_time=start, end_time=recorded_end)

        completed = trip_service.complete_trip(trip.id)

        assert completed.status == "completed"
        assert completed.end_time == recorded_end

    def test_fallback_end_time_uses_local_clock(self, make_trip):
        """A fallback must be stamped on the company's own wall clock, not UTC.

        Trip forms collect local time (UTC+3 here), so a UTC fallback sits
        three hours behind a start_time entered minutes ago and rejects it.
        """
        from app.models.base import local_now

        now = local_now()
        trip = make_trip(status="in_progress", start_time=now.replace(microsecond=0))

        completed = trip_service.complete_trip(trip.id)

        assert completed.status == "completed"
        # Within a minute of the local clock, and never the 3-hours-behind UTC one.
        assert abs((completed.end_time - now).total_seconds()) < 60

    def test_with_explicit_end_time_and_distance(self, make_trip):
        trip = make_trip(status="in_progress", odometer_start=1000.0)
        end = datetime(2026, 7, 7, 17, 0)
        completed = trip_service.complete_trip(trip.id, end_time=end, distance_km=42.5)
        assert completed.end_time == end
        assert completed.distance_km == 42.5
        assert completed.odometer_end == 1042.5

    def test_odometer_bumps_vehicle(self, make_vehicle, make_trip):
        vehicle = make_vehicle(odometer=1000.0)
        trip = make_trip(vehicle=vehicle, status="in_progress", odometer_start=1000.0)
        trip_service.complete_trip(trip.id, distance_km=42.5)
        from extensions import db

        db.session.refresh(vehicle)
        assert vehicle.odometer == 1042.5

    def test_no_odometer_start_skips_end_calc(self, make_trip):
        trip = make_trip(status="in_progress", odometer_start=None)
        completed = trip_service.complete_trip(trip.id, distance_km=10)
        assert completed.odometer_end is None
        assert completed.distance_km == 10

    def test_string_end_time_and_distance_coerced(self, make_trip):
        trip = make_trip(status="in_progress", odometer_start=500.0)
        completed = trip_service.complete_trip(
            trip.id, end_time="2026-08-08T12:00", distance_km="20"
        )
        assert completed.end_time == datetime(2026, 8, 8, 12, 0)
        assert completed.distance_km == 20.0

    def test_rule11_from_planned_rejected(self, make_trip):
        trip = make_trip(status="planned")
        with pytest.raises(ValueError, match="Only in-progress trips can be completed"):
            trip_service.complete_trip(trip.id)
        assert db_status(trip) == "planned"

    def test_rule11_from_cancelled_rejected(self, make_trip):
        trip = make_trip(status="cancelled")
        with pytest.raises(ValueError, match="Only in-progress trips can be completed"):
            trip_service.complete_trip(trip.id)

    def test_rule11_from_completed_rejected(self, make_trip):
        trip = make_trip(status="completed")
        with pytest.raises(ValueError, match="Only in-progress trips can be completed"):
            trip_service.complete_trip(trip.id)

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.complete_trip(999)


class TestCancelTrip:
    def test_from_planned(self, make_trip):
        trip = make_trip(status="planned")
        assert trip_service.cancel_trip(trip.id).status == "cancelled"

    def test_from_in_progress(self, make_trip):
        trip = make_trip(status="in_progress")
        assert trip_service.cancel_trip(trip.id).status == "cancelled"

    def test_rule12_from_completed_rejected(self, make_trip):
        trip = make_trip(status="completed")
        with pytest.raises(ValueError, match="Only planned or in-progress trips can be cancelled"):
            trip_service.cancel_trip(trip.id)
        assert db_status(trip) == "completed"

    def test_rule12_from_cancelled_rejected(self, make_trip):
        trip = make_trip(status="cancelled")
        with pytest.raises(ValueError, match="Only planned or in-progress trips can be cancelled"):
            trip_service.cancel_trip(trip.id)

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.cancel_trip(999)


class TestDeleteTrip:
    @pytest.mark.parametrize("status", ["planned", "in_progress", "completed", "cancelled"])
    def test_rule13_allowed_from_any_status(self, make_trip, status):
        trip = make_trip(status=status)
        trip_service.delete_trip(trip.id)
        assert TripLog.query.count() == 0

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.delete_trip(999)
