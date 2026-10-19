from datetime import date

import pytest

from app.models import FuelLog
from app.services import fuel_service


class TestListFuelLogs:
    def test_empty(self, db):
        assert fuel_service.list_fuel_logs() == ([], 0, 1)

    def test_vehicle_filter(self, make_vehicle, make_fuel):
        v1, v2 = make_vehicle(), make_vehicle()
        make_fuel(vehicle=v1)
        make_fuel(vehicle=v2)
        items, total, _ = fuel_service.list_fuel_logs(vehicle_id=v1.id)
        assert total == 1
        assert items[0].vehicle_id == v1.id

    def test_date_range_filters(self, make_fuel):
        make_fuel(fuel_date=date(2026, 1, 5))
        make_fuel(fuel_date=date(2026, 2, 15))
        make_fuel(fuel_date=date(2026, 3, 25))
        items, total, _ = fuel_service.list_fuel_logs(date_from="2026-02-01", date_to="2026-03-01")
        assert total == 1
        assert items[0].fuel_date == date(2026, 2, 15)

    def test_date_from_only(self, make_fuel):
        make_fuel(fuel_date=date(2026, 1, 5))
        make_fuel(fuel_date=date(2026, 4, 5))
        _, total, _ = fuel_service.list_fuel_logs(date_from=date(2026, 3, 1))
        assert total == 1

    def test_bad_date_filter_raises_value_error(self, make_fuel):
        with pytest.raises(ValueError, match="Invalid date_from"):
            fuel_service.list_fuel_logs(date_from="not-a-date")

    def test_order_fuel_date_desc(self, make_vehicle, make_fuel):
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1))
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 6, 1))
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 3, 1))
        items, _, _ = fuel_service.list_fuel_logs()
        dates = [log.fuel_date for log in items]
        assert dates == sorted(dates, reverse=True)


class TestGetFuelLog:
    def test_returns_log(self, make_fuel):
        log = make_fuel()
        assert fuel_service.get_fuel_log(log.id).id == log.id

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            fuel_service.get_fuel_log(999)


class TestCreateFuelLog:
    def test_valid_with_computed_total(self, db, make_vehicle):
        vehicle = make_vehicle()
        log = fuel_service.create_fuel_log({
            "vehicle_id": str(vehicle.id),
            "fuel_date": "2026-10-09",
            "liters": "100",
            "cost_per_liter": "1.5",
        })
        assert log.total_cost == 150.0
        assert db.session.get(FuelLog, log.id) is not None

    def test_explicit_total_cost_kept(self, make_vehicle):
        vehicle = make_vehicle()
        log = fuel_service.create_fuel_log({
            "vehicle_id": vehicle.id,
            "fuel_date": "2026-10-09",
            "liters": "100",
            "cost_per_liter": "1.5",
            "total_cost": "999.99",
        })
        assert log.total_cost == 999.99

    def test_rule14_missing_vehicle(self, app):
        with pytest.raises(ValueError, match="Vehicle not found"):
            fuel_service.create_fuel_log({
                "fuel_date": "2026-10-09", "liters": "10",
            })

    def test_rule14_unresolvable_vehicle(self, app):
        with pytest.raises(ValueError, match="Vehicle not found"):
            fuel_service.create_fuel_log({
                "vehicle_id": 999, "fuel_date": "2026-10-09", "liters": "10",
            })

    def test_rule14_missing_fuel_date(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Fuel date is required"):
            fuel_service.create_fuel_log({"vehicle_id": vehicle.id, "liters": "10"})

    def test_rule14_missing_liters(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Liters is required"):
            fuel_service.create_fuel_log({
                "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
            })

    def test_rule14_liters_zero(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Liters must be greater than 0"):
            fuel_service.create_fuel_log({
                "vehicle_id": vehicle.id, "fuel_date": "2026-10-09", "liters": "0",
            })

    def test_rule14_liters_negative(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Liters must be greater than 0"):
            fuel_service.create_fuel_log({
                "vehicle_id": vehicle.id, "fuel_date": "2026-10-09", "liters": "-3",
            })

    def test_rule15_negative_cost_per_liter(self, make_vehicle):
        vehicle = make_vehicle()
        with pytest.raises(ValueError, match="Cost per liter cannot be negative"):
            fuel_service.create_fuel_log({
                "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
                "liters": "10", "cost_per_liter": "-0.5",
            })

    def test_rule16_blank_total_cost_computed(self, make_vehicle):
        vehicle = make_vehicle()
        log = fuel_service.create_fuel_log({
            "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
            "liters": "20", "cost_per_liter": "3", "total_cost": "",
        })
        assert log.total_cost == 60.0

    def test_rule17_odometer_bump(self, make_vehicle):
        vehicle = make_vehicle(odometer=5000.0)
        fuel_service.create_fuel_log({
            "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
            "liters": "10", "odometer": "7000",
        })
        from extensions import db

        db.session.refresh(vehicle)
        assert vehicle.odometer == 7000.0

    def test_rule17_odometer_lower_ignored(self, make_vehicle):
        vehicle = make_vehicle(odometer=5000.0)
        fuel_service.create_fuel_log({
            "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
            "liters": "10", "odometer": "4000",
        })
        from extensions import db

        db.session.refresh(vehicle)
        assert vehicle.odometer == 5000.0


class TestUpdateFuelLog:
    def test_updates_fields(self, make_fuel):
        log = make_fuel()
        updated = fuel_service.update_fuel_log(log.id, {"supplier": "Total", "receipt_ref": "R-42"})
        assert updated.supplier == "Total"
        assert updated.receipt_ref == "R-42"

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            fuel_service.update_fuel_log(999, {"supplier": "x"})

    def test_liters_change_recomputes_total(self, make_fuel):
        log = make_fuel(liters=50.0, cost_per_liter=2.0, total_cost=None)
        updated = fuel_service.update_fuel_log(log.id, {"liters": "75"})
        assert updated.liters == 75.0
        assert updated.total_cost == 150.0

    def test_rule14_liters_zero_on_update(self, make_fuel):
        log = make_fuel()
        with pytest.raises(ValueError, match="Liters must be greater than 0"):
            fuel_service.update_fuel_log(log.id, {"liters": "0"})

    def test_rule15_negative_cpl_on_update(self, make_fuel):
        log = make_fuel()
        with pytest.raises(ValueError, match="Cost per liter cannot be negative"):
            fuel_service.update_fuel_log(log.id, {"cost_per_liter": "-1"})

    def test_rule17_odometer_bump_on_update(self, make_vehicle, make_fuel):
        vehicle = make_vehicle(odometer=100.0)
        log = make_fuel(vehicle=vehicle)
        fuel_service.update_fuel_log(log.id, {"odometer": "250"})
        from extensions import db

        db.session.refresh(vehicle)
        assert vehicle.odometer == 250.0

    def test_vehicle_move_on_update(self, make_vehicle, make_fuel):
        a, b = make_vehicle(), make_vehicle()
        log = make_fuel(vehicle=a)
        updated = fuel_service.update_fuel_log(log.id, {"vehicle_id": b.id})
        assert updated.vehicle_id == b.id


class TestDeleteFuelLog:
    def test_deletes(self, make_fuel):
        log = make_fuel()
        fuel_service.delete_fuel_log(log.id)
        assert FuelLog.query.count() == 0

    def test_missing_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            fuel_service.delete_fuel_log(999)


class TestFuelStats:
    def test_empty_stats_shape(self, db):
        stats = fuel_service.fuel_stats()
        assert stats == {
            "total_liters": 0,
            "total_cost": 0,
            "avg_cost_per_liter": 0.0,
            "by_vehicle": {},
        }

    def test_totals_and_average(self, make_fuel):
        make_fuel(liters=100.0, cost_per_liter=2.0, total_cost=None)
        make_fuel(liters=50.0, cost_per_liter=1.0, total_cost=None)
        stats = fuel_service.fuel_stats()
        assert stats["total_liters"] == 150.0
        assert stats["total_cost"] == 250.0
        assert round(stats["avg_cost_per_liter"], 4) == round(250.0 / 150.0, 4)

    def test_by_vehicle_shape(self, make_vehicle, make_fuel):
        v1, v2 = make_vehicle(), make_vehicle()
        make_fuel(vehicle=v1, liters=10.0, cost_per_liter=2.0, total_cost=None)
        make_fuel(vehicle=v1, liters=5.0, cost_per_liter=2.0, total_cost=None)
        make_fuel(vehicle=v2, liters=40.0, cost_per_liter=1.0, total_cost=None)
        stats = fuel_service.fuel_stats()
        assert stats["by_vehicle"][v1.id] == {"liters": 15.0, "cost": 30.0}
        assert stats["by_vehicle"][v2.id] == {"liters": 40.0, "cost": 40.0}

    def test_vehicle_scoped_stats(self, make_vehicle, make_fuel):
        v1, v2 = make_vehicle(), make_vehicle()
        make_fuel(vehicle=v1, liters=10.0, cost_per_liter=2.0, total_cost=None)
        make_fuel(vehicle=v2, liters=999.0, cost_per_liter=2.0, total_cost=None)
        stats = fuel_service.fuel_stats(vehicle_id=v1.id)
        assert stats["total_liters"] == 10.0
        assert v2.id not in stats["by_vehicle"]
