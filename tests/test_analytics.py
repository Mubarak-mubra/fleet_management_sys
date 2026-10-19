"""Fuel efficiency (km/L) and per-trip cost analytics.

Two rollups over data the fleet already records:

- ``fuel_service.fuel_efficiency`` — fill-to-fill km/L: distance between two
  fill-ups divided by the liters added at the second one.
- ``trip_service.trip_cost`` — fuel + maintenance booked to a trip's vehicle
  while the trip ran, plus a cost-per-km figure.

Both are date/odometer-windowed, so a reading outside the window or an
untrustworthy odometer must never leak into the numbers.
"""

from datetime import date, datetime, timedelta

import pytest

from app.services import fuel_service, trip_service


# ------------------------------------------------------------ fuel efficiency


class TestFuelEfficiency:
    def test_empty_returns_zeroed_result(self, db):
        stats = fuel_service.fuel_efficiency()
        assert stats["intervals"] == []
        assert stats["by_vehicle"] == {}
        assert stats["interval_count"] == 0
        assert stats["avg_km_per_liter"] == 0.0
        assert stats["total_km"] == 0.0
        assert stats["total_liters"] == 0.0

    def test_single_fill_makes_no_interval(self, make_vehicle, make_fuel):
        """One fill-up has no prior reading to measure distance against."""
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        stats = fuel_service.fuel_efficiency()
        assert stats["interval_count"] == 0
        assert stats["by_vehicle"] == {}

    def test_two_fills_compute_km_per_liter(self, make_vehicle, make_fuel):
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 10), liters=80.0, odometer=1400.0)

        stats = fuel_service.fuel_efficiency()
        assert stats["interval_count"] == 1
        # 400 km / 80 L = 5.0 km/L — liters of the SECOND fill are charged.
        assert stats["avg_km_per_liter"] == pytest.approx(5.0)
        assert stats["total_km"] == pytest.approx(400.0)
        assert stats["total_liters"] == pytest.approx(80.0)

        interval = stats["intervals"][0]
        assert interval["km"] == pytest.approx(400.0)
        assert interval["liters"] == pytest.approx(80.0)
        assert interval["km_per_liter"] == pytest.approx(5.0)
        assert interval["vehicle_id"] == vehicle.id
        assert interval["date"] == date(2026, 1, 10)

    def test_three_fills_chain_each_pair(self, make_vehicle, make_fuel):
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=50.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 8), liters=50.0, odometer=1200.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 15), liters=100.0, odometer=1600.0)

        stats = fuel_service.fuel_efficiency()
        assert stats["interval_count"] == 2
        assert [i["km"] for i in stats["intervals"]] == pytest.approx([200.0, 400.0])
        # weighted: 600 km / 150 L = 4.0 (NOT the mean of 4.0 and 2.0 = 3.0... )
        # 200/50 = 4.0, 400/100 = 4.0 -> both mean and weighted agree at 4.0
        assert stats["avg_km_per_liter"] == pytest.approx(4.0)

    def test_weighted_average_not_mean_of_ratios(self, make_vehicle, make_fuel):
        """A 1,000 km interval must outweigh a 100 km one.

        intervals: 100 km / 10 L = 10 km/L, then 1,000 km / 200 L = 5 km/L.
        mean of ratios = (10 + 5) / 2 = 7.5 km/L  (wrong: weighs a 100 km
                                                    leg like a 1,000 km one)
        weighted       = 1,100 / 210 = 5.24 km/L  (right)
        """
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 5), liters=10.0, odometer=1100.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 9), liters=200.0, odometer=2100.0)

        stats = fuel_service.fuel_efficiency()
        assert stats["avg_km_per_liter"] == pytest.approx(1100.0 / 210.0)
        assert stats["avg_km_per_liter"] != pytest.approx(7.5)

    def test_missing_odometer_is_skipped(self, make_vehicle, make_fuel):
        """A gap in the ruler means the pair either side of it is unmeasurable."""
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 8), liters=100.0, odometer=None)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 15), liters=100.0, odometer=1400.0)

        stats = fuel_service.fuel_efficiency()
        # Only 1400 - 1000 survives: the middle reading is dropped entirely.
        assert stats["interval_count"] == 1
        assert stats["intervals"][0]["km"] == pytest.approx(400.0)

    def test_backwards_odometer_is_skipped(self, make_vehicle, make_fuel):
        """Odometer replaced or a typo: distance would be negative."""
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=5000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 8), liters=100.0, odometer=4000.0)

        stats = fuel_service.fuel_efficiency()
        assert stats["interval_count"] == 0
        assert stats["avg_km_per_liter"] == 0.0

    def test_same_odometer_is_skipped(self, make_vehicle, make_fuel):
        """Zero distance would divide into an infinite km/L."""
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 8), liters=100.0, odometer=1000.0)

        assert fuel_service.fuel_efficiency()["interval_count"] == 0

    def test_zero_liter_fills_are_rejected_by_the_schema(self, db, make_vehicle):
        """liters is CHECK-constrained > 0, so the divisor can never be zero.

        Pinned here too: if that constraint were dropped, a zero-liter fill
        would make the service divide by zero.
        """
        from sqlalchemy.exc import IntegrityError

        from app.models import FuelLog

        vehicle = make_vehicle()
        db.session.add(
            FuelLog(vehicle_id=vehicle.id, fuel_date=date(2026, 1, 1), liters=0.0, odometer=1000.0)
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_vehicles_are_not_mixed_together(self, make_vehicle, make_fuel):
        """Distance is only ever measured within one vehicle's own readings."""
        v1, v2 = make_vehicle(), make_vehicle()
        make_fuel(vehicle=v1, fuel_date=date(2026, 1, 1), liters=50.0, odometer=1000.0)
        make_fuel(vehicle=v1, fuel_date=date(2026, 1, 8), liters=50.0, odometer=1500.0)
        make_fuel(vehicle=v2, fuel_date=date(2026, 1, 1), liters=50.0, odometer=90000.0)
        make_fuel(vehicle=v2, fuel_date=date(2026, 1, 8), liters=50.0, odometer=90500.0)

        stats = fuel_service.fuel_efficiency()
        assert stats["interval_count"] == 2
        assert set(stats["by_vehicle"]) == {v1.id, v2.id}
        assert stats["by_vehicle"][v1.id]["km_per_liter"] == pytest.approx(10.0)
        assert stats["by_vehicle"][v2.id]["km_per_liter"] == pytest.approx(10.0)
        assert stats["avg_km_per_liter"] == pytest.approx(10.0)

    def test_vehicle_filter_restricts_scope(self, make_vehicle, make_fuel):
        v1, v2 = make_vehicle(), make_vehicle()
        make_fuel(vehicle=v1, fuel_date=date(2026, 1, 1), liters=50.0, odometer=1000.0)
        make_fuel(vehicle=v1, fuel_date=date(2026, 1, 8), liters=50.0, odometer=1500.0)
        make_fuel(vehicle=v2, fuel_date=date(2026, 1, 1), liters=50.0, odometer=90000.0)
        make_fuel(vehicle=v2, fuel_date=date(2026, 1, 8), liters=50.0, odometer=91000.0)

        stats = fuel_service.fuel_efficiency(vehicle_id=v1.id)
        assert set(stats["by_vehicle"]) == {v1.id}
        assert stats["interval_count"] == 1
        assert stats["avg_km_per_liter"] == pytest.approx(10.0)

    def test_interval_dates_come_from_the_second_fill(self, make_vehicle, make_fuel):
        """The interval is *closed* by the second fill — that's its date."""
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=50.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 3, 20), liters=50.0, odometer=1500.0)
        assert fuel_service.fuel_efficiency()["intervals"][0]["date"] == date(2026, 3, 20)


# ----------------------------------------------------------------- trip cost


class TestTripCost:
    def test_no_records_returns_zero(self, make_vehicle, make_trip):
        vehicle = make_vehicle()
        trip = make_trip(vehicle=vehicle, start_time=datetime(2026, 1, 1, 8, 0))
        cost = trip_service.trip_cost(trip.id)
        assert cost["fuel_cost"] == 0.0
        assert cost["maintenance_cost"] == 0.0
        assert cost["total"] == 0.0
        assert cost["cost_per_km"] is None

    def test_fuel_and_maintenance_in_window_are_summed(
        self, make_vehicle, make_trip, make_fuel, make_maintenance
    ):
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 1, 8, 0),
            end_time=datetime(2026, 1, 3, 17, 0),
            distance_km=100.0,
        )
        # 50 L @ 1.5 = 75.0 on Jan 2 (inside)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 2), liters=50.0, cost_per_liter=1.5)
        # 250.0 on Jan 3 (inside)
        make_maintenance(vehicle=vehicle, performed_date=date(2026, 1, 3), cost=250.0)

        cost = trip_service.trip_cost(trip.id)
        assert cost["fuel_cost"] == pytest.approx(75.0)
        assert cost["maintenance_cost"] == pytest.approx(250.0)
        assert cost["total"] == pytest.approx(325.0)
        assert cost["cost_per_km"] == pytest.approx(3.25)
        assert cost["open"] is False

    def test_fuel_before_window_is_excluded(
        self, make_vehicle, make_trip, make_fuel
    ):
        """A fill-up from a month earlier never belongs to this trip."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 2, 10, 8, 0),
            end_time=datetime(2026, 2, 11, 17, 0),
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 10), liters=50.0, cost_per_liter=1.5)

        assert trip_service.trip_cost(trip.id)["fuel_cost"] == 0.0

    def test_fuel_after_window_is_excluded(self, make_vehicle, make_trip, make_fuel):
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 2, 10, 8, 0),
            end_time=datetime(2026, 2, 11, 17, 0),
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 3, 1), liters=50.0, cost_per_liter=1.5)

        assert trip_service.trip_cost(trip.id)["fuel_cost"] == 0.0

    def test_window_boundaries_are_inclusive(self, make_vehicle, make_trip, make_fuel):
        """A fill on the departure day and one on the return day both count."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 2, 10, 8, 0),
            end_time=datetime(2026, 2, 12, 17, 0),
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 2, 10), liters=10.0, cost_per_liter=1.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 2, 12), liters=20.0, cost_per_liter=1.0)

        assert trip_service.trip_cost(trip.id)["fuel_cost"] == pytest.approx(30.0)

    def test_other_vehicles_records_are_excluded(
        self, make_vehicle, make_trip, make_fuel, make_maintenance
    ):
        v1, v2 = make_vehicle(), make_vehicle()
        trip = make_trip(
            vehicle=v1,
            start_time=datetime(2026, 1, 1, 8, 0),
            end_time=datetime(2026, 1, 3, 17, 0),
        )
        make_fuel(vehicle=v2, fuel_date=date(2026, 1, 2), liters=50.0, cost_per_liter=1.5)
        make_maintenance(vehicle=v2, performed_date=date(2026, 1, 2), cost=400.0)

        cost = trip_service.trip_cost(trip.id)
        assert cost["fuel_cost"] == 0.0
        assert cost["maintenance_cost"] == 0.0
        assert cost["total"] == 0.0

    def test_expenses_are_not_charged_to_the_trip(
        self, make_vehicle, make_trip, make_expense
    ):
        """Insurance/wages in the window are period costs, not trip costs."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 1, 8, 0),
            end_time=datetime(2026, 1, 3, 17, 0),
            distance_km=100.0,
        )
        make_expense(vehicle=vehicle, expense_date=date(2026, 1, 2), amount=9999.0)

        assert trip_service.trip_cost(trip.id)["total"] == 0.0

    def test_zero_distance_gives_no_cost_per_km(
        self, make_vehicle, make_trip, make_fuel
    ):
        """Division by zero must not become a crash or a fake infinity."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 1, 8, 0),
            end_time=datetime(2026, 1, 3, 17, 0),
            distance_km=0.0,
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 2), liters=50.0, cost_per_liter=1.5)

        cost = trip_service.trip_cost(trip.id)
        assert cost["total"] == pytest.approx(75.0)
        assert cost["cost_per_km"] is None

    def test_distance_falls_back_to_odometer_difference(
        self, make_vehicle, make_trip, make_fuel
    ):
        """Older rows may only carry odometer readings, never distance_km."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 1, 8, 0),
            end_time=datetime(2026, 1, 3, 17, 0),
            distance_km=None,
            odometer_start=1000.0,
            odometer_end=1250.0,
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 2), liters=50.0, cost_per_liter=1.5)

        cost = trip_service.trip_cost(trip.id)
        assert cost["distance_km"] == pytest.approx(250.0)
        assert cost["cost_per_km"] == pytest.approx(75.0 / 250.0)

    def test_open_trip_is_flagged_and_priced_to_today(
        self, make_vehicle, make_trip, make_fuel
    ):
        """A trip still running is an estimate, and says so."""
        vehicle = make_vehicle()
        today = date.today()
        trip = make_trip(vehicle=vehicle, start_time=datetime(2026, 1, 1, 8, 0), status="in_progress")
        make_fuel(vehicle=vehicle, fuel_date=today, liters=50.0, cost_per_liter=1.5)

        cost = trip_service.trip_cost(trip.id)
        assert cost["open"] is True
        assert cost["end"] == today
        assert cost["fuel_cost"] == pytest.approx(75.0)

    def test_open_trip_end_never_precedes_start(self, make_vehicle, make_trip):
        """A start date in the future must not produce a reversed window."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2099, 1, 1, 8, 0),
            status="planned",
        )
        cost = trip_service.trip_cost(trip.id)
        assert cost["end"] >= cost["start"]

    def test_completed_trip_without_end_time_is_not_open(
        self, make_vehicle, make_trip, make_fuel
    ):
        """Finished, but the end timestamp was never recorded.

        Such a trip must not be priced 'up to today' — the window clamps to
        the start day instead.
        """
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 1, 8, 0),
            status="completed",
            end_time=None,
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=50.0, cost_per_liter=1.5)
        # booked weeks later: belongs to no settled trip
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 3, 1), liters=50.0, cost_per_liter=1.5)

        cost = trip_service.trip_cost(trip.id)
        assert cost["open"] is False
        assert cost["end"] == date(2026, 1, 1)
        assert cost["fuel_cost"] == pytest.approx(75.0)

    def test_cancelled_trip_does_not_sweep_later_fuel(
        self, make_vehicle, make_trip, make_fuel
    ):
        """A cancelled trip never accrued costs after it was called off."""
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 5, 8, 0),
            status="cancelled",
            end_time=None,
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 3, 1), liters=100.0, cost_per_liter=1.5)

        cost = trip_service.trip_cost(trip.id)
        assert cost["open"] is False
        assert cost["end"] == date(2026, 1, 5)
        assert cost["total"] == 0.0

    def test_missing_trip_raises_lookup_error(self, app):
        with pytest.raises(LookupError):
            trip_service.trip_cost(999)


# ------------------------------------------------------------- route surface


class TestAnalyticsRender:
    """The numbers only matter if a user can see them."""

    def test_trip_detail_shows_cost_breakdown(self, client, make_vehicle, make_trip, make_fuel):
        vehicle = make_vehicle()
        trip = make_trip(
            vehicle=vehicle,
            start_time=datetime(2026, 1, 1, 8, 0),
            end_time=datetime(2026, 1, 3, 17, 0),
            distance_km=100.0,
        )
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 2), liters=50.0, cost_per_liter=1.5)

        body = client.get(f"/trips/{trip.id}/").get_data(as_text=True)
        assert "Trip cost" in body
        assert "Fuel in window" in body
        assert "$75.00" in body
        assert "Cost per km" in body

    def test_trip_detail_without_distance_omits_cost_per_km(
        self, client, make_vehicle, make_trip
    ):
        vehicle = make_vehicle()
        trip = make_trip(vehicle=vehicle, distance_km=0.0)
        body = client.get(f"/trips/{trip.id}/").get_data(as_text=True)
        assert "Trip cost" in body
        # no distance -> no per-km figure rendered as a stat
        assert "km</b>" not in body or "cost_per_km" not in body

    def test_fuel_list_renders_efficiency_panel(self, client, make_vehicle, make_fuel):
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 10), liters=80.0, odometer=1400.0)

        body = client.get("/fuel/").get_data(as_text=True)
        assert "Fuel efficiency" in body
        # 400 km / 80 L = 5.0; the value sits inside <b>...</b> before the unit
        assert "<b>5.0</b> km/L average" in body

    def test_fuel_list_without_data_explains_what_is_missing(self, client, db):
        body = client.get("/fuel/").get_data(as_text=True)
        assert "Not enough data yet" in body

    def test_vehicle_detail_shows_efficiency(self, client, make_vehicle, make_fuel):
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 10), liters=80.0, odometer=1400.0)

        body = client.get(f"/vehicles/{vehicle.id}/").get_data(as_text=True)
        assert "km/L efficiency" in body

    def test_vehicle_detail_hides_efficiency_when_unmeasurable(
        self, client, make_vehicle, make_fuel
    ):
        """No second odometer -> no number, rather than a fake 0.0."""
        vehicle = make_vehicle()
        make_fuel(vehicle=vehicle, fuel_date=date(2026, 1, 1), liters=100.0, odometer=1000.0)

        body = client.get(f"/vehicles/{vehicle.id}/").get_data(as_text=True)
        assert "km/L efficiency" not in body
