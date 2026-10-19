"""Driver routes: registration UI, card assignment, and the trip dropdown.

Uses the project's flash-reading pattern (see tests/test_routes.py header).
"""

from app.models import Driver


def flash_page(client, resp):
    assert resp.status_code in (302, 303), resp.status_code
    page = client.get(resp.headers["Location"])
    return page.get_data(as_text=True)


# ---- list / detail ---------------------------------------------------------


def test_list_shows_registered_drivers(client, make_driver):
    make_driver(name="Abdi Ali", card_code="DRV-0001")
    body = client.get("/drivers/").get_data(as_text=True)
    assert "Abdi Ali" in body
    assert "DRV-0001" in body


def test_list_empty_state(client):
    body = client.get("/drivers/").get_data(as_text=True)
    assert "No drivers found" in body


def test_list_filters_by_status(client, make_driver):
    make_driver(name="Active One", status="active")
    make_driver(name="Suspended One", status="suspended")
    body = client.get("/drivers/?status=suspended").get_data(as_text=True)
    assert "Suspended One" in body
    assert "Active One" not in body


def test_list_search_by_card(client, make_driver):
    make_driver(name="Abdi Ali", card_code="DRV-7777")
    make_driver(name="Ahmed Omar", card_code="DRV-8888")
    body = client.get("/drivers/?q=7777").get_data(as_text=True)
    assert "Abdi Ali" in body
    assert "Ahmed Omar" not in body


def test_detail_renders_driver_and_card(client, make_driver):
    driver = make_driver(name="Abdi Ali", card_code="DRV-0001", phone="+1 555 010 2030")
    body = client.get(f"/drivers/{driver.id}/").get_data(as_text=True)
    assert "Abdi Ali" in body
    assert "DRV-0001" in body
    assert "+1 555 010 2030" in body


def test_detail_lists_their_trips(client, make_driver, make_vehicle, make_trip):
    driver = make_driver()
    make_trip(vehicle=make_vehicle(), driver_id=driver.id, driver_name=driver.name,
              destination="Site A")
    body = client.get(f"/drivers/{driver.id}/").get_data(as_text=True)
    assert "Site A" in body


# ---- create ----------------------------------------------------------------


def test_create_via_form_assigns_card(client, db):
    resp = client.post("/drivers/new", data={"name": "Ahmed Omar"}, follow_redirects=False)
    body = flash_page(client, resp)
    assert "Ahmed Omar" in body
    driver = Driver.query.one()
    assert driver.card_code == "DRV-0001"


def test_create_via_form_with_explicit_card(client, db):
    client.post("/drivers/new", data={"name": "Mohamed Hassan", "card_code": "FLEET-42"})
    assert Driver.query.one().card_code == "FLEET-42"


def test_create_rejects_blank_name(client, db):
    resp = client.post("/drivers/new", data={"name": "   "})
    body = flash_page(client, resp)
    assert "Name is required" in body
    assert Driver.query.count() == 0


def test_create_rejects_duplicate_card(client, db, make_driver):
    make_driver(card_code="DRV-0001")
    resp = client.post("/drivers/new", data={"name": "Other", "card_code": "DRV-0001"})
    body = flash_page(client, resp)
    assert "already assigned" in body
    assert Driver.query.count() == 1


def test_create_form_offers_auto_assign_hint(client):
    body = client.get("/drivers/new").get_data(as_text=True)
    assert "auto-assign" in body.lower()


# ---- edit ------------------------------------------------------------------


def test_edit_updates_and_keeps_card(client, make_driver):
    driver = make_driver(name="Old Name", card_code="DRV-0500")
    resp = client.post(
        f"/drivers/{driver.id}/edit",
        data={"name": "New Name", "card_code": ""},
    )
    body = flash_page(client, resp)
    assert "New Name" in body
    assert driver.card_code == "DRV-0500", "blank card must not wipe the issued card"


def test_edit_reassigns_card(client, make_driver):
    driver = make_driver(card_code="DRV-0500")
    client.post(f"/drivers/{driver.id}/edit", data={"name": driver.name, "card_code": "DRV-0900"})
    assert driver.card_code == "DRV-0900"


def test_edit_unknown_driver_is_404(client):
    assert client.post("/drivers/999/edit", data={"name": "X"}).status_code == 404


# ---- delete ----------------------------------------------------------------


def test_delete_removes_driver(client, make_driver):
    driver = make_driver()
    resp = client.post(f"/drivers/{driver.id}/delete")
    body = flash_page(client, resp)
    assert "Driver deleted" in body
    assert Driver.query.count() == 0


def test_delete_blocked_by_active_trip(client, make_driver, make_vehicle, make_trip):
    driver = make_driver()
    make_trip(vehicle=make_vehicle(), driver_id=driver.id, driver_name=driver.name,
              status="in_progress")
    resp = client.post(f"/drivers/{driver.id}/delete")
    body = flash_page(client, resp)
    assert "active trip" in body
    assert Driver.query.count() == 1


def test_delete_unknown_driver_is_404(client):
    assert client.post("/drivers/999/delete").status_code == 404


# ---- mutations are POST-only ----------------------------------------------


def test_delete_is_post_only(client, make_driver):
    """Forms render on GET; deletion must never."""
    driver = make_driver()
    assert client.get(f"/drivers/{driver.id}/delete").status_code == 405
    # and the create/edit pages are legitimately GETtable form pages
    assert client.get("/drivers/new").status_code == 200
    assert client.get(f"/drivers/{driver.id}/edit").status_code == 200


# ---- the trip form uses registered drivers ---------------------------------


def test_trip_form_offers_registered_drivers(client, make_driver, make_vehicle):
    make_driver(name="Abdi Ali", card_code="DRV-0001")
    body = client.get("/trips/new").get_data(as_text=True)
    assert 'name="driver_id"' in body
    assert "Abdi Ali — DRV-0001" in body
    # the free-text driver box must be gone
    assert 'name="driver_name"' not in body


def test_trip_form_hints_when_no_drivers_registered(client):
    body = client.get("/trips/new").get_data(as_text=True)
    assert "No drivers registered yet" in body
    assert "/drivers/new" in body


def test_trip_form_preselects_current_driver(client, make_driver, make_vehicle, make_trip):
    driver = make_driver(name="Abdi Ali")
    trip = make_trip(vehicle=make_vehicle(), driver_id=driver.id, driver_name=driver.name)
    body = client.get(f"/trips/{trip.id}/edit").get_data(as_text=True)
    assert f'value="{driver.id}" selected' in body


# ---- creating a trip by driver id -----------------------------------------


def test_trip_created_from_driver_id_snapshots_name(client, db, make_vehicle, make_driver):
    driver = make_driver(name="Abdi Ali")
    resp = client.post(
        "/trips/new",
        data={
            "vehicle_id": make_vehicle().id,
            "driver_id": driver.id,
            "purpose": "Haul spoil",
            "origin": "Yard",
            "destination": "Site A",
            "start_time": "2026-01-01T08:00",
        },
    )
    assert resp.status_code == 302
    from app.models import TripLog

    trip = TripLog.query.one()
    assert trip.driver_id == driver.id
    assert trip.driver_name == "Abdi Ali"


def test_trip_rejects_unknown_driver_id(client, db, make_vehicle):
    resp = client.post(
        "/trips/new",
        data={
            "vehicle_id": make_vehicle().id,
            "driver_id": 9999,
            "purpose": "p",
            "origin": "o",
            "destination": "d",
            "start_time": "2026-01-01T08:00",
        },
    )
    body = flash_page(client, resp)
    assert "Driver not found" in body
