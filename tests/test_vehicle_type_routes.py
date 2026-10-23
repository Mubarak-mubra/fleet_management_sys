"""The Vehicle Types section: manage the registry the Type dropdown uses."""
from app.models import Vehicle, VehicleType


def flash_page(client, resp):
    assert resp.status_code in (302, 303), resp.status_code
    page = client.get(resp.headers["Location"])
    return page.get_data(as_text=True)


def test_types_page_renders_as_sidebar_section(client, make_vehicle_type):
    make_vehicle_type(name="Tipper")
    body = client.get("/vehicle-types/").get_data(as_text=True)
    assert "Vehicle Types" in body
    assert "Tipper" in body
    assert 'href="/vehicle-types/"' in body


def test_types_page_highlights_its_own_sidebar_entry(client):
    body = client.get("/vehicle-types/").get_data(as_text=True)
    # Slice from the Vehicles anchor up to the next anchor, so we inspect
    # only that one <a> and not the Vehicle Types link that follows it.
    chunk = body.split('href="/vehicles/"', 1)[1].split("<a ", 1)[0]
    assert 'class="active"' not in chunk


def test_sidebar_lists_vehicle_types_after_vehicles(client):
    body = client.get("/vehicles/").get_data(as_text=True)
    assert 'href="/vehicle-types/"' in body


def test_more_page_links_to_vehicle_types(client):
    body = client.get("/more/").get_data(as_text=True)
    assert 'href="/vehicle-types/"' in body


def test_add_type_via_post(client):
    body = flash_page(
        client,
        client.post("/vehicle-types/new", data={"name": "Water Tanker"}),
    )
    assert "Vehicle type Water Tanker added" in body
    assert VehicleType.query.filter_by(name="Water Tanker").count() == 1


def test_add_duplicate_type_flashes_error(client, make_vehicle_type):
    make_vehicle_type(name="Tipper")
    body = flash_page(
        client, client.post("/vehicle-types/new", data={"name": "tipper"})
    )
    assert "already exists" in body
    assert VehicleType.query.count() == 1


def test_delete_unused_type(client, make_vehicle_type):
    t = make_vehicle_type(name="Grader")
    body = flash_page(client, client.post(f"/vehicle-types/{t.id}/delete"))
    assert "Vehicle type deleted" in body
    assert VehicleType.query.count() == 0


def test_delete_type_in_use_is_blocked(client, make_vehicle_type, make_vehicle):
    t = make_vehicle_type(name="Tipper")
    make_vehicle(plate_number="GC-B1", vehicle_type="Tipper")
    body = flash_page(client, client.post(f"/vehicle-types/{t.id}/delete"))
    assert "vehicle uses this type" in body
    assert VehicleType.query.count() == 1


def test_delete_unknown_type_is_404(client):
    assert client.post("/vehicle-types/9999/delete").status_code == 404


def test_vehicle_form_offers_registered_types(client, make_vehicle_type):
    make_vehicle_type(name="Tipper")
    make_vehicle_type(name="Grader")
    body = client.get("/vehicles/new").get_data(as_text=True)
    # Jinja leaves a space where the (unselected) "selected" attribute goes.
    assert 'value="Grader"' in body
    assert 'value="Tipper"' in body
    assert "Add it under Vehicle Types" in body


def test_edit_form_keeps_legacy_unregistered_value(client, make_vehicle):
    """A vehicle typed before the registry existed still shows its value."""
    vehicle = make_vehicle(vehicle_type="submarine")
    body = client.get(f"/vehicles/{vehicle.id}/edit").get_data(as_text=True)
    assert "(not registered)" in body


def test_vehicle_post_stores_canonical_spelling(client, make_vehicle_type):
    make_vehicle_type(name="Tipper")
    client.post(
        "/vehicles/new",
        data={"name": "T1", "plate_number": "GC-C1", "vehicle_type": "tipper"},
    )
    assert Vehicle.query.filter_by(plate_number="GC-C1").one().vehicle_type == "Tipper"
