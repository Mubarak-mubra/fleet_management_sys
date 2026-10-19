"""Trip status renders in Somali.

The DB keeps the English enum (``planned``/``in_progress``/``completed``/
``cancelled``) because filtering, badge CSS classes and the API all key off
it; the Somali labels are applied at render time by the ``trip_status``
template filter. These tests pin both halves of that contract.
"""

import re

from app.models.trip import TRIP_STATUSES, TRIP_STATUS_LABELS

# The four labels the user asked for, keyed by stored value.
SOMALI = {
    "planned": "isku diyaarin bixit",
    "in_progress": "baxay",
    "completed": "dhameystiray",
    "cancelled": "lajoojiyay",
}

# Pages that render a trip status badge.
TRIP_BADGE_PAGES = ["/trips/", "/", "/drivers/"]


def test_label_map_covers_every_status_exactly():
    """Every status has a label, and no stray keys sneak in."""
    assert set(TRIP_STATUS_LABELS) == set(TRIP_STATUSES)
    assert TRIP_STATUS_LABELS == SOMALI


def test_labels_are_distinct_and_non_empty():
    values = list(TRIP_STATUS_LABELS.values())
    assert all(v.strip() for v in values), values
    assert len(set(values)) == len(values), f"duplicate labels: {values}"


def test_labels_are_lowercase_somali_not_title_cased():
    """Regression: these must not be re-routed through |title."""
    for label in TRIP_STATUS_LABELS.values():
        assert label == label.lower(), label


def test_stored_values_remain_english():
    """The translation must be display-only — the enum is untouched."""
    assert TRIP_STATUSES == ("planned", "in_progress", "completed", "cancelled")


def test_filter_renders_somali_labels(client, make_vehicle, make_trip):
    vehicle = make_vehicle()
    for status in TRIP_STATUSES:
        make_trip(vehicle=vehicle, status=status, destination=f"Dest {status}")
    body = client.get("/trips/").get_data(as_text=True)
    for status, label in SOMALI.items():
        assert f'badge badge-{status}">{label}</span>' in body, (
            f"{status}: expected rendered label {label!r}"
        )


def test_trip_detail_renders_somali_status(client, make_vehicle, make_trip):
    trip = make_trip(vehicle=make_vehicle(), status="in_progress")
    body = client.get(f"/trips/{trip.id}/").get_data(as_text=True)
    assert ">baxay</span>" in body


def test_status_dropdown_keeps_english_value_with_somali_label(client):
    """The filter <option> must submit the English value (that is what
    /trips/?status= matches) while showing the Somali text."""
    body = client.get("/trips/").get_data(as_text=True)
    for status, label in SOMALI.items():
        assert f'<option value="{status}"' in body, f"{status} option missing"
        assert f'>{label}</option>' in body, f"{status}: label {label!r} not shown"


def test_trip_form_select_keeps_english_value_with_somali_label(client, db):
    """Submitting the form must still post the English enum."""
    body = client.get("/trips/new").get_data(as_text=True)
    for status, label in SOMALI.items():
        assert f'<option value="{status}"' in body
        assert f'>{label}</option>' in body


def test_no_english_status_words_render_on_trips_page(client, make_vehicle, make_trip):
    """Guard against a template regressing to |replace|title for trip status."""
    vehicle = make_vehicle()
    for status in TRIP_STATUSES:
        make_trip(vehicle=vehicle, status=status)
    body = client.get("/trips/").get_data(as_text=True)
    badges = re.findall(r'badge badge-\w+">([^<]+)</span>', body)
    rendered = {b.strip() for b in badges}
    for status in TRIP_STATUSES:
        english = status.replace("_", " ").title()
        assert english not in rendered, f"{english!r} rendered instead of Somali"
