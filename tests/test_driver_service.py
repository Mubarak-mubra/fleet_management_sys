"""Driver registration and fleet-card assignment.

Drivers register once and are then picked from a dropdown on the trip form
instead of typing a name. Each driver holds a unique card code.
"""

import pytest

from app.models import Driver, TripLog
from app.services import driver_service, trip_service


# ---- model -----------------------------------------------------------------


def test_driver_defaults(db, make_driver):
    driver = make_driver(name="Abdi Ali", card_code="DRV-0001")
    assert driver.status == "active"
    assert driver.card_status == "active"
    assert driver.created_at is not None
    assert driver.is_available is True


def test_is_available_false_when_status_inactive(make_driver):
    assert make_driver(status="inactive").is_available is False
    assert make_driver(card_status="lost").is_available is False
    assert make_driver(status="suspended", card_status="expired").is_available is False


def test_card_code_is_unique_at_the_db_level(db, make_driver):
    make_driver(card_code="DRV-0001")
    with pytest.raises(Exception):
        db.session.add(Driver(name="Duplicate", card_code="DRV-0001"))
        db.session.commit()
    db.session.rollback()


# ---- create ----------------------------------------------------------------


def test_create_driver_generates_card_when_blank(db):
    driver = driver_service.create_driver({"name": "Ahmed Omar"})
    assert driver.card_code == "DRV-0001"


def test_create_driver_issued_codes_are_sequential(db):
    first = driver_service.create_driver({"name": "Ahmed Omar"})
    second = driver_service.create_driver({"name": "Mohamed Hassan"})
    assert (first.card_code, second.card_code) == ("DRV-0001", "DRV-0002")


def test_create_driver_honours_explicit_card(db):
    driver = driver_service.create_driver({"name": "Farhan Yusuf", "card_code": "FLEET-77"})
    assert driver.card_code == "FLEET-77"


def test_create_driver_rejects_duplicate_card_case_insensitive(db):
    driver_service.create_driver({"name": "Ahmed Omar", "card_code": "DRV-0009"})
    with pytest.raises(ValueError, match="already assigned"):
        driver_service.create_driver({"name": "Other", "card_code": "drv-0009"})


def test_create_driver_skips_taken_auto_codes(db):
    """A hand-picked card must not be re-issued by the auto generator."""
    driver_service.create_driver({"name": "Manual", "card_code": "DRV-0001"})
    auto = driver_service.create_driver({"name": "Auto"})
    assert auto.card_code == "DRV-0002"
    assert Driver.query.filter_by(card_code="DRV-0001").count() == 1


def test_create_driver_requires_name(db):
    with pytest.raises(ValueError, match="Name is required"):
        driver_service.create_driver({"name": "   "})


def test_create_driver_rejects_bad_status(db):
    with pytest.raises(ValueError, match="Invalid driver status"):
        driver_service.create_driver({"name": "X", "status": "retired"})


def test_create_driver_rejects_bad_card_status(db):
    with pytest.raises(ValueError, match="Invalid card status"):
        driver_service.create_driver({"name": "X", "card_status": "destroyed"})


def test_create_driver_rejects_overlong_card(db):
    with pytest.raises(ValueError, match="at most 30"):
        driver_service.create_driver({"name": "X", "card_code": "C" * 31})


# ---- phone validation ------------------------------------------------------


@pytest.mark.parametrize("phone", ["+252 61 442 7715", "0614427715", "+252614427715"])
def test_create_driver_accepts_valid_phones(db, phone):
    driver = driver_service.create_driver({"name": "X", "phone": phone})
    assert driver.phone == phone


@pytest.mark.parametrize("phone", ["12345", "not-a-number", "12 34 abc 56"])
def test_create_driver_rejects_invalid_phones(db, phone):
    with pytest.raises(ValueError, match="Phone number"):
        driver_service.create_driver({"name": "X", "phone": phone})


def test_blank_phone_stores_none(db):
    assert driver_service.create_driver({"name": "X", "phone": "  "}).phone is None


def test_update_driver_rejects_invalid_phone(db, make_driver):
    driver = make_driver()
    with pytest.raises(ValueError, match="Phone number"):
        driver_service.update_driver(driver.id, {"phone": "nope"})


# ---- update ----------------------------------------------------------------


def test_update_driver_keeps_card_when_blank_submitted(db, make_driver):
    """The form always submits card_code; blank must not wipe an issued card."""
    driver = make_driver(card_code="DRV-0100")
    updated = driver_service.update_driver(driver.id, {"name": "Renamed", "card_code": ""})
    assert updated.card_code == "DRV-0100"
    assert updated.name == "Renamed"


def test_update_driver_can_reassign_card(db, make_driver):
    driver = make_driver(card_code="DRV-0100")
    updated = driver_service.update_driver(driver.id, {"card_code": "DRV-9000"})
    assert updated.card_code == "DRV-9000"


def test_update_driver_rejects_card_owned_by_another(db, make_driver):
    make_driver(card_code="DRV-0100")
    other = make_driver(card_code="DRV-0200")
    with pytest.raises(ValueError, match="already assigned"):
        driver_service.update_driver(other.id, {"card_code": "DRV-0100"})


def test_update_driver_can_keep_its_own_card(db, make_driver):
    driver = make_driver(card_code="DRV-0100")
    updated = driver_service.update_driver(driver.id, {"card_code": "DRV-0100"})
    assert updated.card_code == "DRV-0100"


def test_update_driver_unknown_raises_lookup(db):
    with pytest.raises(LookupError):
        driver_service.update_driver(9999, {"name": "X"})


def test_update_driver_clearable_fields(db, make_driver):
    driver = make_driver(phone="+1 555 010 2030", license_number="DL-1", notes="n")
    updated = driver_service.update_driver(
        driver.id, {"phone": "", "license_number": "", "notes": ""}
    )
    assert updated.phone is None
    assert updated.license_number is None
    assert updated.notes is None


# ---- list / get / options --------------------------------------------------


def test_get_driver_unknown_raises_lookup(app):
    with pytest.raises(LookupError):
        driver_service.get_driver(4242)


def test_list_drivers_filters_by_status(make_driver):
    make_driver(name="Active One", status="active")
    make_driver(name="Suspended One", status="suspended")
    items, total, _ = driver_service.list_drivers(status="suspended")
    assert total == 1
    assert items[0].name == "Suspended One"


def test_list_drivers_search_covers_card_and_name(make_driver):
    make_driver(name="Abdi Ali", card_code="DRV-3001")
    make_driver(name="Ahmed Omar", card_code="DRV-3002")
    _, total, _ = driver_service.list_drivers(q="3001")
    assert total == 1
    _, total, _ = driver_service.list_drivers(q="ahmed")
    assert total == 1


def test_driver_options_sorted_active_first(make_driver):
    make_driver(name="Zebra", status="active")
    make_driver(name="Alpha", status="suspended")
    names = [d.name for d in driver_service.driver_options()]
    assert names == ["Zebra", "Alpha"]


# ---- delete ----------------------------------------------------------------


def test_delete_driver_with_no_trips(make_driver):
    driver = make_driver()
    driver_service.delete_driver(driver.id)
    assert Driver.query.get(driver.id) is None


def test_delete_driver_refused_while_trip_is_open(db, make_driver, make_vehicle, make_trip):
    driver = make_driver()
    make_trip(vehicle=make_vehicle(), driver_id=driver.id, driver_name=driver.name,
              status="in_progress")
    with pytest.raises(ValueError, match="active trip"):
        driver_service.delete_driver(driver.id)


def test_delete_driver_keeps_completed_trip_history(db, make_driver, make_vehicle, make_trip):
    driver = make_driver()
    trip = make_trip(vehicle=make_vehicle(), driver_id=driver.id, driver_name=driver.name,
                     status="completed")
    trip_id = trip.id
    driver_service.delete_driver(driver.id)

    survivor = TripLog.query.get(trip_id)
    assert survivor is not None
    assert survivor.driver_id is None, "FK should be nulled, not cascade-deleted"
    assert survivor.driver_name == "Test Driver", "name snapshot must survive deletion"


# ---- summary ---------------------------------------------------------------


def test_driver_summary_counts(make_driver, make_vehicle, make_trip):
    driver = make_driver()
    vehicle = make_vehicle()
    make_trip(vehicle=vehicle, driver_id=driver.id, driver_name=driver.name,
              status="completed", distance_km=10.0)
    make_trip(vehicle=vehicle, driver_id=driver.id, driver_name=driver.name,
              status="planned", distance_km=None)
    summary = driver_service.driver_summary(driver.id)
    assert summary["trips"] == 2
    assert summary["open_trips"] == 1
    assert summary["total_distance_km"] == 10.0


def test_driver_summary_zero_for_new_driver(make_driver):
    summary = driver_service.driver_summary(make_driver().id)
    assert summary["trips"] == 0
    assert summary["open_trips"] == 0
    assert summary["last_trip"] is None
