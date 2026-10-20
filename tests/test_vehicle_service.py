import pytest

from app.models import Vehicle
from app.services import vehicle_service


class TestListVehicles:
    def test_empty_returns_empty_tuple(self, db):
        assert vehicle_service.list_vehicles() == ([], 0, 1)

    def test_status_filter(self, make_vehicle):
        make_vehicle(status="active")
        make_vehicle(status="maintenance")
        items, total, pages = vehicle_service.list_vehicles(status="maintenance")
        assert total == 1
        assert items[0].status == "maintenance"

    def test_search_q_is_case_insensitive(self, make_vehicle):
        make_vehicle(name="Excavator CAT-320", plate_number="GC-SEARCH")
        make_vehicle(name="Dump Truck", plate_number="GC-OTHER")
        items, total, _ = vehicle_service.list_vehicles(q="excav")
        assert total == 1
        assert items[0].name == "Excavator CAT-320"
        items, total, _ = vehicle_service.list_vehicles(q="gc-search")
        assert total == 1

    def test_search_covers_make_and_model(self, make_vehicle):
        make_vehicle(make="Caterpillar", model="320")
        items, total, _ = vehicle_service.list_vehicles(q="caterp")
        assert total == 1
        items, total, _ = vehicle_service.list_vehicles(q="320")
        assert total == 1

    def test_order_by_status_then_name(self, db):
        db.session.add(Vehicle(name="B Crane", plate_number="GC-OB1", status="active"))
        db.session.add(Vehicle(name="A Dozer", plate_number="GC-OB2", status="active"))
        db.session.add(Vehicle(name="C Loader", plate_number="GC-OB3", status="maintenance"))
        db.session.commit()
        items, _, _ = vehicle_service.list_vehicles()
        assert [v.name for v in items] == ["A Dozer", "B Crane", "C Loader"]

    def test_pagination_tuple(self, db):
        for i in range(20):
            db.session.add(Vehicle(name=f"V {i}", plate_number=f"GC-L{i}"))
        db.session.commit()
        items, total, pages = vehicle_service.list_vehicles(page=2, per_page=15)
        assert total == 20
        assert pages == 2
        assert len(items) == 5


class TestGetVehicle:
    def test_returns_vehicle(self, make_vehicle):
        vehicle = make_vehicle()
        assert vehicle_service.get_vehicle(vehicle.id).id == vehicle.id

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            vehicle_service.get_vehicle(999)


class TestCreateVehicle:
    def test_valid_create(self, db, make_vehicle_type):
        make_vehicle_type(name="crane")
        vehicle = vehicle_service.create_vehicle(
            {"name": "Crane Liebherr", "plate_number": "GC-100", "vehicle_type": "crane",
             "make": "Liebherr", "model": "LTR 1220", "year": "2021", "status": "active",
             "odometer": "500", "fuel_capacity_liters": "300", "notes": "yard unit"}
        )
        assert vehicle.id is not None
        stored = db.session.get(Vehicle, vehicle.id)
        assert stored.plate_number == "GC-100"
        assert stored.year == 2021
        assert stored.odometer == 500.0

    def test_unknown_keys_ignored(self, app):
        vehicle = vehicle_service.create_vehicle(
            {"name": "X", "plate_number": "GC-UK", "bogus_key": "whatever"}
        )
        assert vehicle.id is not None

    def test_rule1_missing_name(self, app):
        with pytest.raises(ValueError, match="Name is required"):
            vehicle_service.create_vehicle({"plate_number": "GC-N1"})

    def test_rule1_blank_name(self, app):
        with pytest.raises(ValueError, match="Name is required"):
            vehicle_service.create_vehicle({"name": "   ", "plate_number": "GC-N2"})

    def test_rule1_missing_plate(self, app):
        with pytest.raises(ValueError, match="Plate number is required"):
            vehicle_service.create_vehicle({"name": "X"})

    def test_rule2_duplicate_plate(self, make_vehicle):
        make_vehicle(plate_number="GC-DUP1")
        with pytest.raises(ValueError, match="Plate number already exists"):
            vehicle_service.create_vehicle({"name": "Clone", "plate_number": "GC-DUP1"})

    def test_rule2_duplicate_plate_case_insensitive(self, make_vehicle):
        make_vehicle(plate_number="GC-ABC")
        with pytest.raises(ValueError, match="Plate number already exists"):
            vehicle_service.create_vehicle({"name": "Clone", "plate_number": "gc-abc"})

    def test_rule3_invalid_status(self, app):
        with pytest.raises(ValueError, match="Invalid vehicle status"):
            vehicle_service.create_vehicle(
                {"name": "X", "plate_number": "GC-S1", "status": "flying"}
            )

    def test_registered_vehicle_type_is_accepted(self, app, make_vehicle_type):
        """Types are user-registered; a known one saves fine."""
        make_vehicle_type(name="submarine")
        vehicle = vehicle_service.create_vehicle(
            {"name": "X", "plate_number": "GC-T1", "vehicle_type": "submarine"}
        )
        assert vehicle.vehicle_type == "submarine"

    def test_unregistered_vehicle_type_rejected(self, app):
        with pytest.raises(ValueError, match="Unknown vehicle type"):
            vehicle_service.create_vehicle(
                {"name": "X", "plate_number": "GC-T2", "vehicle_type": "submarine"}
            )

    def test_vehicle_type_saved_with_registry_spelling(self, app, make_vehicle_type):
        """Case-insensitive match, canonical spelling stored."""
        make_vehicle_type(name="Tipper")
        vehicle = vehicle_service.create_vehicle(
            {"name": "X", "plate_number": "GC-T3", "vehicle_type": "TIPPER"}
        )
        assert vehicle.vehicle_type == "Tipper"

    def test_rule4_year_too_low(self, app):
        with pytest.raises(ValueError, match="Year must be between 1900 and 2100"):
            vehicle_service.create_vehicle(
                {"name": "X", "plate_number": "GC-Y1", "year": "1800"}
            )

    def test_rule4_year_too_high(self, app):
        with pytest.raises(ValueError, match="Year must be between 1900 and 2100"):
            vehicle_service.create_vehicle(
                {"name": "X", "plate_number": "GC-Y2", "year": "2200"}
            )

    def test_rule4_year_not_a_number(self, app):
        with pytest.raises(ValueError, match="Invalid year"):
            vehicle_service.create_vehicle(
                {"name": "X", "plate_number": "GC-Y3", "year": "brand new"}
            )

    def test_year_blank_is_accepted(self, app):
        vehicle = vehicle_service.create_vehicle(
            {"name": "X", "plate_number": "GC-Y4", "year": ""}
        )
        assert vehicle.year is None

    def test_defaults_applied(self, app):
        vehicle = vehicle_service.create_vehicle({"name": "X", "plate_number": "GC-D9"})
        assert vehicle.vehicle_type == "other"
        assert vehicle.status == "active"


class TestUpdateVehicle:
    def test_updates_fields(self, make_vehicle):
        vehicle = make_vehicle()
        updated = vehicle_service.update_vehicle(
            vehicle.id, {"name": "Renamed", "make": "Komatsu", "year": "2019"}
        )
        assert updated.name == "Renamed"
        assert updated.make == "Komatsu"
        assert updated.year == 2019

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            vehicle_service.update_vehicle(999, {"name": "x"})

    def test_rule2_plate_change_to_existing_rejected(self, make_vehicle):
        a = make_vehicle(plate_number="GC-UA")
        make_vehicle(plate_number="GC-UB")
        with pytest.raises(ValueError, match="Plate number already exists"):
            vehicle_service.update_vehicle(a.id, {"plate_number": "GC-UB"})

    def test_rule2_plate_change_case_insensitive(self, make_vehicle):
        a = make_vehicle(plate_number="GC-UA2")
        make_vehicle(plate_number="GC-UB2")
        with pytest.raises(ValueError, match="Plate number already exists"):
            vehicle_service.update_vehicle(a.id, {"plate_number": "gc-ub2"})

    def test_own_plate_case_change_allowed(self, make_vehicle):
        vehicle = make_vehicle(plate_number="GC-OWN")
        updated = vehicle_service.update_vehicle(vehicle.id, {"plate_number": "gc-own"})
        assert updated.plate_number == "gc-own"

    def test_rule3_status_change_valid(self, make_vehicle):
        vehicle = make_vehicle()
        updated = vehicle_service.update_vehicle(vehicle.id, {"status": "maintenance"})
        assert updated.status == "maintenance"

    def test_rule3_status_change_invalid(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Invalid vehicle status"):
            vehicle_service.update_vehicle(vehicle.id, {"status": "lost"})


class TestDeleteVehicle:
    def test_delete_removes_vehicle(self, make_vehicle):
        vehicle = make_vehicle()
        vehicle_service.delete_vehicle(vehicle.id)
        assert Vehicle.query.count() == 0

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            vehicle_service.delete_vehicle(999)

    def test_rule5_open_planned_trip_blocks_delete(self, make_vehicle, make_trip):
        vehicle = make_vehicle()
        make_trip(vehicle=vehicle, status="planned")
        with pytest.raises(ValueError, match="Cannot delete vehicle with an active trip"):
            vehicle_service.delete_vehicle(vehicle.id)
        assert Vehicle.query.count() == 1

    def test_rule5_in_progress_trip_blocks_delete(self, make_vehicle, make_trip):
        vehicle = make_vehicle()
        make_trip(vehicle=vehicle, status="in_progress")
        with pytest.raises(ValueError, match="Cannot delete vehicle with an active trip"):
            vehicle_service.delete_vehicle(vehicle.id)
        assert Vehicle.query.count() == 1

    def test_delete_allowed_with_completed_trip(self, make_vehicle, make_trip):
        vehicle = make_vehicle()
        make_trip(vehicle=vehicle, status="completed")
        vehicle_service.delete_vehicle(vehicle.id)
        assert Vehicle.query.count() == 0


class TestVehicleSummary:
    def test_keys_and_values(self, db, make_vehicle, make_trip, make_fuel, make_maintenance):
        from datetime import datetime

        vehicle = make_vehicle()
        make_trip(vehicle=vehicle, status="completed", start_time=datetime(2026, 1, 1))
        make_trip(vehicle=vehicle, status="planned", start_time=datetime(2026, 2, 1))
        make_trip(vehicle=vehicle, status="in_progress", start_time=datetime(2026, 3, 1))
        make_fuel(vehicle=vehicle, liters=40.0, cost_per_liter=2.0, total_cost=None)
        make_maintenance(vehicle=vehicle, cost=75.0)

        summary = vehicle_service.vehicle_summary(vehicle.id)
        assert set(summary) == {
            "trips", "total_fuel_liters", "total_fuel_cost",
            "total_maintenance_cost", "last_trip", "open_trips",
        }
        assert summary["trips"] == 3
        assert summary["total_fuel_liters"] == 40.0
        assert summary["total_fuel_cost"] == 80.0
        assert summary["total_maintenance_cost"] == 75.0
        assert summary["open_trips"] == 2
        assert summary["last_trip"].start_time == datetime(2026, 3, 1)

    def test_empty_vehicle_summary(self, make_vehicle):
        vehicle = make_vehicle()
        summary = vehicle_service.vehicle_summary(vehicle.id)
        assert summary["trips"] == 0
        assert summary["last_trip"] is None
        assert summary["open_trips"] == 0
        assert summary["total_fuel_cost"] == 0.0

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            vehicle_service.vehicle_summary(999)
