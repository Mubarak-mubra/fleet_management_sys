"""Vehicle type registry: create/delete, canonical matching, usage guards."""
import pytest

from app.services import vehicle_type_service


class TestCreateType:
    def test_creates_a_type(self, app):
        t = vehicle_type_service.create_type({"name": "Tipper"})
        assert t.name == "Tipper"
        assert vehicle_type_service.type_options() == ["Tipper"]

    def test_name_is_required(self, app):
        with pytest.raises(ValueError, match="Type name is required"):
            vehicle_type_service.create_type({"name": "   "})

    def test_name_length_capped_at_50(self, app):
        with pytest.raises(ValueError, match="50 characters"):
            vehicle_type_service.create_type({"name": "t" * 51})

    def test_duplicate_is_rejected_case_insensitively(self, app):
        vehicle_type_service.create_type({"name": "Tipper"})
        with pytest.raises(ValueError, match="already exists"):
            vehicle_type_service.create_type({"name": "TIPPER"})


class TestFindRegisteredName:
    def test_matches_case_insensitively_and_returns_canonical(self, app):
        vehicle_type_service.create_type({"name": "Water Tanker"})
        assert vehicle_type_service.find_registered_name("water tanker") == "Water Tanker"
        assert vehicle_type_service.find_registered_name("  Water Tanker ") == "Water Tanker"

    def test_unknown_and_blank_return_none(self, app):
        assert vehicle_type_service.find_registered_name("Grader") is None
        assert vehicle_type_service.find_registered_name("") is None
        assert vehicle_type_service.find_registered_name(None) is None


class TestListTypes:
    def test_reports_usage_counts(self, app, make_vehicle_type, make_vehicle):
        make_vehicle_type(name="Tipper")
        make_vehicle_type(name="Grader")
        make_vehicle(name="Truck A", plate_number="GC-L1", vehicle_type="Tipper")
        make_vehicle(name="Truck B", plate_number="GC-L2", vehicle_type="Tipper")
        # Legacy casing still counts against the registered name.
        make_vehicle(name="Old", plate_number="GC-L3", vehicle_type="tipper")

        rows = vehicle_type_service.list_types()
        assert [(r["type"].name, r["count"]) for r in rows] == [
            ("Grader", 0),
            ("Tipper", 3),
        ]


class TestDeleteType:
    def test_deletes_an_unused_type(self, app):
        t = vehicle_type_service.create_type({"name": "Grader"})
        vehicle_type_service.delete_type(t.id)
        assert vehicle_type_service.type_options() == []

    def test_blocks_delete_while_vehicles_use_it(self, app, make_vehicle_type, make_vehicle):
        make_vehicle_type(name="Tipper")
        make_vehicle(plate_number="GC-D1", vehicle_type="Tipper")
        t = next(
            row["type"]
            for row in vehicle_type_service.list_types()
            if row["type"].name == "Tipper"
        )
        with pytest.raises(ValueError, match="1 vehicle uses this type"):
            vehicle_type_service.delete_type(t.id)
        assert vehicle_type_service.type_options() == ["Tipper"]

    def test_missing_type_raises_lookup(self, app):
        with pytest.raises(LookupError):
            vehicle_type_service.delete_type(9999)
