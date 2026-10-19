from datetime import date

import pytest

from app.models import MaintenanceLog
from app.services import maintenance_service


class TestListMaintenance:
    def test_empty(self, db):
        assert maintenance_service.list_maintenance() == ([], 0, 1)

    def test_vehicle_filter(self, make_vehicle, make_maintenance):
        v1, v2 = make_vehicle(), make_vehicle()
        make_maintenance(vehicle=v1)
        make_maintenance(vehicle=v2)
        items, total, _ = maintenance_service.list_maintenance(vehicle_id=v1.id)
        assert total == 1
        assert items[0].vehicle_id == v1.id

    def test_status_filter(self, make_maintenance):
        make_maintenance(status="completed")
        make_maintenance(status="scheduled")
        items, total, _ = maintenance_service.list_maintenance(status="scheduled")
        assert total == 1
        assert items[0].status == "scheduled"

    def test_order_performed_date_desc(self, make_vehicle, make_maintenance):
        vehicle = make_vehicle()
        make_maintenance(vehicle=vehicle, performed_date=date(2026, 1, 1))
        make_maintenance(vehicle=vehicle, performed_date=date(2026, 8, 1))
        make_maintenance(vehicle=vehicle, performed_date=date(2026, 4, 1))
        items, _, _ = maintenance_service.list_maintenance()
        dates = [log.performed_date for log in items]
        assert dates == sorted(dates, reverse=True)


class TestGetMaintenance:
    def test_returns_record(self, make_maintenance):
        log = make_maintenance()
        assert maintenance_service.get_maintenance(log.id).id == log.id

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            maintenance_service.get_maintenance(999)


class TestCreateMaintenance:
    def test_valid_create(self, db, make_vehicle):
        vehicle = make_vehicle()
        log = maintenance_service.create_maintenance({
            "vehicle_id": str(vehicle.id),
            "maintenance_type": "repair",
            "description": "Fix hydraulics",
            "performed_date": "2026-10-01",
            "next_due_date": "2027-01-01",
            "cost": "250.50",
            "vendor": "Acme Mechanics",
            "status": "completed",
        })
        assert log.cost == 250.50
        assert db.session.get(MaintenanceLog, log.id) is not None

    def test_rule18_missing_vehicle(self, app):
        with pytest.raises(ValueError, match="Vehicle not found"):
            maintenance_service.create_maintenance({
                "description": "d", "performed_date": "2026-10-01",
            })

    def test_rule18_unresolvable_vehicle(self, app):
        with pytest.raises(ValueError, match="Vehicle not found"):
            maintenance_service.create_maintenance({
                "vehicle_id": 999, "description": "d", "performed_date": "2026-10-01",
            })

    def test_rule18_missing_description(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Description is required"):
            maintenance_service.create_maintenance({
                "vehicle_id": vehicle.id, "performed_date": "2026-10-01",
            })

    def test_rule18_missing_performed_date(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Performed date is required"):
            maintenance_service.create_maintenance({
                "vehicle_id": vehicle.id, "description": "d",
            })

    def test_rule19_negative_cost(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Cost cannot be negative"):
            maintenance_service.create_maintenance({
                "vehicle_id": vehicle.id, "description": "d",
                "performed_date": "2026-10-01", "cost": "-10",
            })

    def test_rule20_next_due_before_performed(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="next_due_date cannot be before performed_date"):
            maintenance_service.create_maintenance({
                "vehicle_id": vehicle.id, "description": "d",
                "performed_date": "2026-10-01", "next_due_date": "2026-09-01",
            })

    def test_rule20_next_due_equal_allowed(self, make_vehicle):
        vehicle = make_vehicle()
        log = maintenance_service.create_maintenance({
            "vehicle_id": vehicle.id, "description": "d",
            "performed_date": "2026-10-01", "next_due_date": "2026-10-01",
        })
        assert log.next_due_date == date(2026, 10, 1)

    def test_rule21_invalid_type(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Invalid maintenance type"):
            maintenance_service.create_maintenance({
                "vehicle_id": vehicle.id, "description": "d",
                "performed_date": "2026-10-01", "maintenance_type": "tuneup",
            })

    def test_rule21_invalid_status(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Invalid maintenance status"):
            maintenance_service.create_maintenance({
                "vehicle_id": vehicle.id, "description": "d",
                "performed_date": "2026-10-01", "status": "maybe",
            })


class TestUpdateMaintenance:
    def test_updates_fields(self, make_maintenance):
        log = make_maintenance()
        updated = maintenance_service.update_maintenance(
            log.id, {"cost": "300", "vendor": "Bolt Co"}
        )
        assert updated.cost == 300.0
        assert updated.vendor == "Bolt Co"

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            maintenance_service.update_maintenance(999, {"cost": "1"})

    def test_rule19_negative_cost_on_update(self, make_maintenance):
        log = make_maintenance()
        with pytest.raises(ValueError, match="Cost cannot be negative"):
            maintenance_service.update_maintenance(log.id, {"cost": "-1"})

    def test_rule20_next_due_before_performed_on_update(self, make_maintenance):
        log = make_maintenance(performed_date=date(2026, 5, 5))
        with pytest.raises(ValueError, match="next_due_date cannot be before performed_date"):
            maintenance_service.update_maintenance(log.id, {"next_due_date": "2026-05-01"})

    def test_rule21_invalid_type_on_update(self, make_maintenance):
        log = make_maintenance()
        with pytest.raises(ValueError, match="Invalid maintenance type"):
            maintenance_service.update_maintenance(log.id, {"maintenance_type": "polish"})

    def test_rule18_blank_description_on_update(self, make_maintenance):
        log = make_maintenance()
        with pytest.raises(ValueError, match="Description is required"):
            maintenance_service.update_maintenance(log.id, {"description": "  "})


class TestDeleteMaintenance:
    def test_deletes(self, make_maintenance):
        log = make_maintenance()
        maintenance_service.delete_maintenance(log.id)
        assert MaintenanceLog.query.count() == 0

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            maintenance_service.delete_maintenance(999)


class TestOverdueItems:
    def test_no_args_returns_all_overdue(self, db, make_maintenance):
        make_maintenance(next_due_date=date(2020, 1, 1), status="scheduled")
        make_maintenance(next_due_date=date(2020, 6, 1), status="in_progress")
        items = maintenance_service.overdue_items()
        assert len(items) == 2
        assert [log.next_due_date for log in items] == sorted(
            log.next_due_date for log in items
        )

    def test_excludes_future_due(self, make_maintenance):
        make_maintenance(next_due_date=date(2999, 1, 1), status="scheduled")
        assert maintenance_service.overdue_items() == []

    def test_excludes_completed(self, make_maintenance):
        make_maintenance(next_due_date=date(2020, 1, 1), status="completed")
        assert maintenance_service.overdue_items() == []

    def test_excludes_none_due(self, make_maintenance):
        make_maintenance(next_due_date=None, status="scheduled")
        assert maintenance_service.overdue_items() == []

    def test_vehicle_id_kwarg_filters(self, make_vehicle, make_maintenance):
        v1, v2 = make_vehicle(), make_vehicle()
        make_maintenance(vehicle=v1, next_due_date=date(2020, 1, 1), status="scheduled")
        make_maintenance(vehicle=v2, next_due_date=date(2020, 2, 1), status="scheduled")
        items = maintenance_service.overdue_items(vehicle_id=v1.id)
        assert len(items) == 1
        assert items[0].vehicle_id == v1.id


class TestMaintenanceStats:
    def test_empty_shape(self, db):
        assert maintenance_service.maintenance_stats() == {
            "total_cost": 0,
            "by_type": {},
            "overdue_count": 0,
            "upcoming": [],
        }

    def test_total_cost_and_by_type(self, make_maintenance):
        make_maintenance(maintenance_type="service", cost=100.0)
        make_maintenance(maintenance_type="service", cost=50.0)
        make_maintenance(maintenance_type="tire", cost=400.0)
        stats = maintenance_service.maintenance_stats()
        assert stats["total_cost"] == 550.0
        assert stats["by_type"] == {"service": 150.0, "tire": 400.0}

    def test_overdue_count(self, make_maintenance):
        make_maintenance(next_due_date=date(2020, 1, 1), status="scheduled", cost=0.0)
        make_maintenance(next_due_date=date(2020, 2, 1), status="scheduled", cost=0.0)
        make_maintenance(next_due_date=date(2999, 1, 1), status="scheduled", cost=0.0)
        stats = maintenance_service.maintenance_stats()
        assert stats["overdue_count"] == 2

    def test_upcoming_sorted_and_future_only(self, make_vehicle, make_maintenance):
        vehicle = make_vehicle()
        make_maintenance(vehicle=vehicle, next_due_date=date(2999, 6, 1), status="scheduled", cost=0.0)
        make_maintenance(vehicle=vehicle, next_due_date=date(2999, 1, 1), status="scheduled", cost=0.0)
        make_maintenance(vehicle=vehicle, next_due_date=date(2020, 1, 1), status="scheduled", cost=0.0)
        make_maintenance(vehicle=vehicle, next_due_date=None, status="scheduled", cost=0.0)
        stats = maintenance_service.maintenance_stats()
        due_dates = [log.next_due_date for log in stats["upcoming"]]
        assert due_dates == sorted(due_dates)
        assert all(d >= date.today() for d in due_dates)
        assert len(due_dates) == 2

    def test_vehicle_scoped(self, make_vehicle, make_maintenance):
        v1, v2 = make_vehicle(), make_vehicle()
        make_maintenance(vehicle=v1, cost=100.0)
        make_maintenance(vehicle=v2, cost=900.0)
        stats = maintenance_service.maintenance_stats(vehicle_id=v1.id)
        assert stats["total_cost"] == 100.0
