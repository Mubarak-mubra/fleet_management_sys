# Flash-reading pattern (single pattern used throughout this file):
#   1. POST *without* follow_redirects -> assert the status (302 for validation
#      errors, 302 for successful mutations).
#   2. GET resp.headers["Location"] -> the flash stack renders into that page,
#      so assert the message text with `in body`.
#   3. follow_redirects=True is only used for happy-path bodies where we assert
#      on the destination page itself (never on flash text captured earlier).

from datetime import datetime

from app.models import FuelLog, MaintenanceLog, TripLog, Vehicle


def flash_page(client, resp):
    assert resp.status_code in (302, 303), resp.status_code
    page = client.get(resp.headers["Location"])
    return page.get_data(as_text=True)


# ----------------------------------------------------------------- GET sweep

def test_get_sweep(client):
    expected = {
        "/": 200,
        "/vehicles/": 200,
        "/vehicles/new": 200,
        "/vehicle-types/": 200,
        "/vehicles/999/": 404,
        "/vehicles/999/edit": 404,
        "/trips/": 200,
        "/trips/new": 200,
        "/trips/999/": 404,
        "/trips/999/edit": 404,
        "/drivers/": 200,
        "/drivers/new": 200,
        "/drivers/999/": 404,
        "/drivers/999/edit": 404,
        "/more/": 200,
        "/fuel/": 200,
        "/fuel/new": 200,
        "/fuel/999/edit": 404,
        "/maintenance/": 200,
        "/maintenance/new": 200,
        "/maintenance/999/": 404,
        "/maintenance/999/edit": 404,
        "/nope/": 404,
    }
    for url, status in expected.items():
        assert client.get(url).status_code == status, (url, client.get(url).status_code)


def test_get_sweep_existing_entities(client, make_vehicle, make_trip, make_fuel, make_maintenance):
    vehicle = make_vehicle()
    trip = make_trip(vehicle=vehicle)
    log = make_fuel(vehicle=vehicle)
    maint = make_maintenance(vehicle=vehicle)
    assert client.get(f"/vehicles/{vehicle.id}/").status_code == 200
    assert client.get(f"/vehicles/{vehicle.id}/edit").status_code == 200
    assert client.get(f"/trips/{trip.id}/").status_code == 200
    assert client.get(f"/trips/{trip.id}/edit").status_code == 200
    assert client.get(f"/fuel/{log.id}/edit").status_code == 200
    assert client.get(f"/maintenance/{maint.id}/").status_code == 200
    assert client.get(f"/maintenance/{maint.id}/edit").status_code == 200


# ------------------------------------------------- POST-only routes -> 405

def test_mutation_routes_are_post_only(client):
    post_only = [
        "/vehicles/999/delete",
        "/trips/999/start",
        "/trips/999/complete",
        "/trips/999/cancel",
        "/trips/999/delete",
        "/fuel/999/delete",
        "/maintenance/999/delete",
    ]
    assert len(post_only) == 7
    for url in post_only:
        assert client.get(url).status_code == 405, url


# ------------------------------------------- LookupError -> 404 (id 999)

def test_lookup_error_returns_404(client):
    probes = [
        ("GET", "/vehicles/999/"),
        ("GET", "/vehicles/999/edit"),
        ("POST", "/vehicles/999/delete"),
        ("GET", "/trips/999/"),
        ("GET", "/trips/999/edit"),
        ("POST", "/trips/999/start"),
        ("POST", "/trips/999/complete"),
        ("POST", "/trips/999/cancel"),
        ("POST", "/trips/999/delete"),
        ("GET", "/fuel/999/edit"),
        ("POST", "/fuel/999/delete"),
        ("GET", "/maintenance/999/"),
        ("GET", "/maintenance/999/edit"),
        ("POST", "/maintenance/999/delete"),
    ]
    for method, url in probes:
        resp = client.get(url) if method == "GET" else client.post(url)
        assert resp.status_code == 404, (method, url, resp.status_code)


# --------------------------- ValueError -> flash + 302, never 500 (21 rules)

def test_rule1_missing_name_or_plate_flashed(client):
    body = flash_page(client, client.post("/vehicles/new", data={"plate_number": "GC-R1"}))
    assert "Name is required" in body
    body = flash_page(client, client.post("/vehicles/new", data={"name": "X"}))
    assert "Plate number is required" in body


def test_rule2_duplicate_plate_flashed(client, make_vehicle):
    make_vehicle(plate_number="GC-R2")
    body = flash_page(client, client.post(
        "/vehicles/new", data={"name": "Clone", "plate_number": "gc-r2"}))
    assert "Plate number already exists" in body
    assert Vehicle.query.count() == 1


def test_rule3_invalid_status_flashed(client):
    body = flash_page(client, client.post(
        "/vehicles/new", data={"name": "X", "plate_number": "GC-R3", "status": "flying"}))
    assert "Invalid vehicle status" in body


def test_unregistered_vehicle_type_rejected(client):
    """Type comes from the Vehicle Types registry — unknown values bounce."""
    body = flash_page(client, client.post(
        "/vehicles/new",
        data={"name": "X", "plate_number": "GC-R3b", "vehicle_type": "Water Tanker"}))
    assert "Unknown vehicle type" in body


def test_registered_vehicle_type_accepted(client, make_vehicle_type):
    make_vehicle_type(name="Water Tanker")
    resp = client.post(
        "/vehicles/new",
        data={"name": "X", "plate_number": "GC-R3c", "vehicle_type": "water tanker"},
    )
    assert resp.status_code == 302
    from app.models import Vehicle

    saved = Vehicle.query.filter_by(plate_number="GC-R3c").one()
    # Stored with the registry's canonical spelling, not the typed casing.
    assert saved.vehicle_type == "Water Tanker"


def test_vehicle_form_dropdown_is_built_from_registry(client, make_vehicle_type):
    make_vehicle_type(name="Water Tanker")
    body = client.get("/vehicles/new").get_data(as_text=True)
    assert 'value="Water Tanker"' in body
    assert "/vehicle-types/" in body  # "add it first" link present


def test_rule4_year_out_of_range_flashed(client):
    body = flash_page(client, client.post(
        "/vehicles/new", data={"name": "X", "plate_number": "GC-R4", "year": "1800"}))
    assert "Year must be between 1900 and 2100" in body


def test_rule5_delete_vehicle_with_open_trip_flashed(client, make_vehicle, make_trip):
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, status="planned")
    body = flash_page(client, client.post(f"/vehicles/{vehicle.id}/delete"))
    assert "Cannot delete vehicle with an active trip" in body
    assert Vehicle.query.count() == 1


def test_rule6_trip_without_vehicle_flashed(client):
    body = flash_page(client, client.post("/trips/new", data={
        "driver_name": "A", "purpose": "p", "origin": "o", "destination": "d",
        "start_time": "2026-10-09T08:00",
    }))
    assert "Vehicle not found" in body
    assert TripLog.query.count() == 0


def test_rule7_missing_driver_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/trips/new", data={
        "vehicle_id": vehicle.id, "purpose": "p", "origin": "o", "destination": "d",
        "start_time": "2026-10-09T08:00",
    }))
    assert "Driver name is required" in body


def test_rule8_end_before_start_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/trips/new", data={
        "vehicle_id": vehicle.id, "driver_name": "A", "purpose": "p",
        "origin": "o", "destination": "d",
        "start_time": "2026-10-09T10:00", "end_time": "2026-10-09T09:00",
    }))
    assert "end_time must be after start_time" in body
    assert TripLog.query.count() == 0


def test_rule9_invalid_create_status_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/trips/new", data={
        "vehicle_id": vehicle.id, "driver_name": "A", "purpose": "p",
        "origin": "o", "destination": "d",
        "start_time": "2026-10-09T08:00", "status": "completed",
    }))
    assert "Invalid trip status" in body


def test_rule10_start_twice_flashed(client, make_vehicle, make_trip):
    vehicle = make_vehicle()
    trip = make_trip(vehicle=vehicle, status="planned")
    first = client.post(f"/trips/{trip.id}/start")
    assert first.status_code == 302
    client.get(first.headers["Location"])
    body = flash_page(client, client.post(f"/trips/{trip.id}/start"))
    assert "Only planned trips can be started" in body
    assert db_status(trip) == "in_progress"


def test_rule11_complete_planned_trip_flashed(client, make_vehicle, make_trip):
    vehicle = make_vehicle()
    trip = make_trip(vehicle=vehicle, status="planned")
    body = flash_page(client, client.post(f"/trips/{trip.id}/complete"))
    assert "Only in-progress trips can be completed" in body
    assert db_status(trip) == "planned"


def test_rule12_cancel_completed_trip_flashed(client, make_vehicle, make_trip):
    vehicle = make_vehicle()
    trip = make_trip(vehicle=vehicle, status="completed")
    body = flash_page(client, client.post(f"/trips/{trip.id}/cancel"))
    assert "Only planned or in-progress trips can be cancelled" in body
    assert db_status(trip) == "completed"


def test_rule14_liters_zero_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/fuel/new", data={
        "vehicle_id": vehicle.id, "fuel_date": "2026-10-09", "liters": "0",
    }))
    assert "Liters must be greater than 0" in body
    assert FuelLog.query.count() == 0


def test_rule14_missing_fuel_date_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/fuel/new", data={
        "vehicle_id": vehicle.id, "liters": "10",
    }))
    assert "Fuel date is required" in body


def test_rule15_negative_cost_per_liter_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/fuel/new", data={
        "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
        "liters": "10", "cost_per_liter": "-1",
    }))
    assert "Cost per liter cannot be negative" in body


def test_rule18_missing_description_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "performed_date": "2026-10-01",
    }))
    assert "Description is required" in body


def test_rule19_negative_cost_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "description": "d",
        "performed_date": "2026-10-01", "cost": "-5",
    }))
    assert "Cost cannot be negative" in body
    assert MaintenanceLog.query.count() == 0


def test_rule20_next_due_before_performed_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "description": "d",
        "performed_date": "2026-10-01", "next_due_date": "2026-09-01",
    }))
    assert "next_due_date cannot be before performed_date" in body
    assert MaintenanceLog.query.count() == 0


def test_rule21_invalid_maintenance_type_and_status_flashed(client, make_vehicle):
    vehicle = make_vehicle()
    body = flash_page(client, client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "description": "d",
        "performed_date": "2026-10-01", "maintenance_type": "tuneup",
    }))
    assert "Invalid maintenance type" in body
    body = flash_page(client, client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "description": "d",
        "performed_date": "2026-10-01", "status": "maybe",
    }))
    assert "Invalid maintenance status" in body


# ----------------------------------------------------------- success paths

def test_vehicle_crud_round_trip(client, db, make_vehicle_type):
    assert Vehicle.query.count() == 0
    make_vehicle_type(name="excavator")

    resp = client.post("/vehicles/new", data={
        "name": "Excavator CAT-320", "plate_number": "GC-OK1",
        "vehicle_type": "excavator", "year": "2020",
    })
    assert resp.status_code == 302
    body = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert Vehicle.query.count() == 1
    assert "Vehicle Excavator CAT-320 created" in body

    vehicle = Vehicle.query.first()
    resp = client.post(f"/vehicles/{vehicle.id}/edit", data={
        "name": "Excavator CAT-320 Long Reach", "plate_number": "GC-OK1",
    })
    assert resp.status_code == 302
    assert db.session.get(Vehicle, vehicle.id).name == "Excavator CAT-320 Long Reach"

    resp = client.post(f"/vehicles/{vehicle.id}/delete")
    assert resp.status_code == 302
    assert Vehicle.query.count() == 0


def test_trip_state_machine_planned_to_completed(client, make_vehicle, db):
    vehicle = make_vehicle()
    resp = client.post("/trips/new", data={
        "vehicle_id": vehicle.id, "driver_name": "Abdi Ali", "purpose": "Haul",
        "origin": "Yard", "destination": "Site A",
        "start_time": "2026-10-09T08:00",
    })
    assert resp.status_code == 302
    trip = TripLog.query.first()
    assert trip.status == "planned"

    assert client.post(f"/trips/{trip.id}/start").status_code == 302
    assert db_status(trip) == "in_progress"

    resp = client.post(f"/trips/{trip.id}/complete", data={"distance_km": "30"})
    assert resp.status_code == 302
    trip = db.session.get(TripLog, trip.id)
    assert trip.status == "completed"
    assert trip.distance_km == 30.0
    assert trip.end_time is not None


def test_trip_state_machine_planned_to_cancelled(client, make_vehicle, db):
    vehicle = make_vehicle()
    resp = client.post("/trips/new", data={
        "vehicle_id": vehicle.id, "driver_name": "Ama", "purpose": "Move",
        "origin": "Yard", "destination": "Site B",
        "start_time": "2026-10-10T09:00",
    })
    assert resp.status_code == 302
    trip = TripLog.query.first()
    assert client.post(f"/trips/{trip.id}/cancel").status_code == 302
    assert db_status(trip) == "cancelled"


def test_trip_delete_route(client, make_vehicle, db):
    vehicle = make_vehicle()
    client.post("/trips/new", data={
        "vehicle_id": vehicle.id, "driver_name": "K", "purpose": "p",
        "origin": "o", "destination": "d", "start_time": "2026-10-09T08:00",
    })
    trip = TripLog.query.first()
    resp = client.post(f"/trips/{trip.id}/delete")
    assert resp.status_code == 302
    assert TripLog.query.count() == 0


def test_fuel_create_success_computes_total(client, make_vehicle, db):
    vehicle = make_vehicle()
    resp = client.post("/fuel/new", data={
        "vehicle_id": vehicle.id, "fuel_date": "2026-10-09",
        "liters": "100", "cost_per_liter": "1.5",
    })
    assert resp.status_code == 302
    body = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Fuel log of 100.0 L created" in body
    log = FuelLog.query.first()
    assert log.total_cost == 150.0


def test_maintenance_create_success(client, make_vehicle, db):
    vehicle = make_vehicle()
    resp = client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "description": "Oil change",
        "performed_date": "2026-10-01", "next_due_date": "2027-01-01",
        "cost": "120",
    })
    assert resp.status_code == 302
    body = client.get(resp.headers["Location"]).get_data(as_text=True)
    assert "Maintenance &#39;Oil change&#39; created" in body or "Maintenance 'Oil change' created" in body
    log = MaintenanceLog.query.first()
    assert log.cost == 120.0


def test_cascade_delete_of_clean_vehicle(client, db, make_vehicle, make_trip, make_fuel, make_maintenance):
    assert Vehicle.query.count() == 0

    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, status="completed")
    make_fuel(vehicle=vehicle)
    make_maintenance(vehicle=vehicle)

    resp = client.post(f"/vehicles/{vehicle.id}/delete")
    assert resp.status_code == 302
    assert Vehicle.query.count() == 0
    assert TripLog.query.count() == 0
    assert FuelLog.query.count() == 0
    assert MaintenanceLog.query.count() == 0


def test_fuel_and_maintenance_delete_routes(client, make_vehicle, db):
    vehicle = make_vehicle()
    client.post("/fuel/new", data={
        "vehicle_id": vehicle.id, "fuel_date": "2026-10-09", "liters": "10",
    })
    client.post("/maintenance/new", data={
        "vehicle_id": vehicle.id, "description": "Check",
        "performed_date": "2026-10-01",
    })
    log = FuelLog.query.first()
    maint = MaintenanceLog.query.first()
    assert client.post(f"/fuel/{log.id}/delete").status_code == 302
    assert client.post(f"/maintenance/{maint.id}/delete").status_code == 302
    assert FuelLog.query.count() == 0
    assert MaintenanceLog.query.count() == 0


def test_list_routes_render_with_and_without_filters(client, make_vehicle, make_trip):
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle)
    assert client.get("/vehicles/?status=active&q=GC").status_code == 200
    assert client.get("/trips/?status=planned").status_code == 200
    assert client.get(f"/trips/?vehicle_id={vehicle.id}").status_code == 200
    assert client.get("/fuel/?date_from=2026-01-01&date_to=2026-12-31").status_code == 200
    assert client.get("/maintenance/?status=completed").status_code == 200


def test_trip_list_filters_by_project_and_counts(client, make_trip, make_project):
    """How many trips went to a specific project? Filter by it — the header
    count answers the question, and only that project's trips render."""
    project = make_project(name="Harbour Job")
    make_trip(destination="Site A")  # unassigned
    make_trip(destination="Site B", project_id=project.id)

    body = client.get(f"/trips/?project_id={project.id}").get_data(as_text=True)
    assert "Site B" in body
    assert "Site A" not in body
    assert "1 trip</p>" in body  # header shows the count for this project
    assert f'value="{project.id}" selected' in body  # filter stays selected

    # Without the filter both trips are back and the count updates.
    body = client.get("/trips/").get_data(as_text=True)
    assert "Site A" in body and "Site B" in body
    assert "2 trips</p>" in body


def test_trip_detail_shows_project_link(client, make_trip, make_project):
    project = make_project(name="Harbour Job")
    linked = make_trip(destination="Site B", project_id=project.id)
    lonely = make_trip(destination="Site A")

    body = client.get(f"/trips/{linked.id}/").get_data(as_text=True)
    assert project.code in body and project.name in body
    assert f'/projects/{project.id}/' in body

    body = client.get(f"/trips/{lonely.id}/").get_data(as_text=True)
    assert "No project" in body


def test_trip_detail_renders_currency_not_function_repr(client, make_trip):
    """Regression: the per-km line used {{ currency_symbol }} (the function
    itself), printing '<function ...>' instead of '$'."""
    trip = make_trip(
        status="completed",
        end_time=datetime(2026, 1, 1, 12, 0),
        distance_km=30.0,
    )
    body = client.get(f"/trips/{trip.id}/").get_data(as_text=True)
    assert "<function" not in body
    assert "$0.00/km" in body  # nothing spent yet — shown as money, not repr


def test_bad_fuel_date_filter_renders_200_with_error(client):
    resp = client.get("/fuel/?date_from=not-a-date")
    assert resp.status_code == 200
    assert "Invalid date_from" in resp.get_data(as_text=True)


def test_no_cross_test_leakage(client):
    assert Vehicle.query.count() == 0
    assert TripLog.query.count() == 0
    assert FuelLog.query.count() == 0
    assert MaintenanceLog.query.count() == 0


def db_status(trip):
    from extensions import db

    return db.session.get(TripLog, trip.id).status
