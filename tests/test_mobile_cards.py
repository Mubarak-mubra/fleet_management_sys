"""Mobile table → card conversion.

On phones tables are unusable, so every data <td> must carry a
data-label="Column" attribute that CSS turns into a card field label via
::before { content: attr(data-label) }. These tests pin that contract for all
list pages plus the dashboard's inline tables.
"""

import re

from extensions import db

# (url, exact data-label cell count). Counts are exact on the seeded fixture
# so a dropped column fails loudly instead of sliding past a loose minimum.
# List pages paginate at 15 rows, so rows shown = min(seed count, 15).
LIST_PAGES = [
    ("/vehicles/", 25),      # 5 rows x 5 data columns
    ("/trips/", 135),        # 15 of 18 trips x 9 data columns
    ("/fuel/", 105),         # 15 of 16 fuel logs x 7 data columns
    ("/maintenance/", 70),   # 10 rows x 7 data columns
    ("/projects/", 18),      # 3 rows x 6 data columns
    ("/vehicles/types/", 10),  # 5 of 5 registered types x 2 data columns
    ("/", 45),               # dashboard: recent trips (5x4) + recent fuel (5x2)
                             # + overdue table reusing the "Date" label
]

# Every row partial must label its data cells (actions cell has no label).
ROW_PARTIALS = {
    "app/templates/vehicles/_row.html": 5,
    "app/templates/trips/_row.html": 9,
    "app/templates/fuel/_row.html": 7,
    "app/templates/maintenance/_row.html": 7,
    "app/templates/projects/_row.html": 6,
}


def _seed(app):
    with app.app_context():
        db.create_all()
        from app.cli import _seed as seed_rows

        seed_rows()
        db.session.commit()


def test_row_partials_label_every_data_cell():
    """Guards the source templates, not just a rendered page."""
    from pathlib import Path

    for path, expected in ROW_PARTIALS.items():
        html = Path(path).read_text()
        labels = re.findall(r'<td data-label="([^"]+)"', html)
        assert len(labels) == expected, (
            f"{path}: expected {expected} labelled cells, got {len(labels)} {labels}"
        )
        # no blank or whitespace-only labels — an empty ::before looks broken
        assert all(lbl.strip() for lbl in labels), f"{path}: blank data-label in {labels}"


def test_actions_cell_is_unlabelled_and_classed():
    """The buttons cell must NOT get a label (it is not a data field)."""
    from pathlib import Path

    for path in ROW_PARTIALS:
        html = Path(path).read_text()
        assert 'class="cell-actions"' in html, f"{path}: missing cell-actions class"
        assert re.search(
            r'<td class="cell-actions">', html
        ), f"{path}: actions cell must carry no data-label"


def test_list_pages_render_labelled_cards(app, client):
    _seed(app)
    for path, minimum in LIST_PAGES:
        body = client.get(path).get_data(as_text=True)
        labels = re.findall(r'<td data-label="([^"]*)"', body)
        assert len(labels) == minimum, (
            f"{path}: expected {minimum} data-label cells, got {len(labels)}"
        )
        assert all(lbl.strip() for lbl in labels), f"{path}: blank data-label rendered"
        # thead stays in the DOM for desktop but must exist so tables still
        # render as real tables at wide widths
        if path != "/":
            assert "<thead>" in body, f"{path}: thead removed — desktop table broken"


def test_no_data_label_cell_renders_empty(app, client):
    """A card row with an empty value looks like a rendering bug."""
    _seed(app)
    body = client.get("/trips/").get_data(as_text=True)
    empty = re.findall(r'data-label="[^"]*">\s*</td>', body)
    assert not empty, f"empty card fields rendered: {empty[:3]}"


def test_card_conversion_is_mobile_only():
    """The card stack must live inside a max-width media query so desktop
    tables are untouched."""
    from pathlib import Path

    css = Path("app/static/css/style.css").read_text()
    # find the mobile block that hides thead
    blocks = re.findall(r"@media \(max-width: (\d+)px\) \{(.*?)\n\}", css, re.S)
    hiding = [bp for bp, body in blocks if "thead" in body and "display: none" in body]
    assert hiding, "no media query hides thead — cards would break desktop tables"
    # every one of them must be a max-width (mobile-down) query, never min-width
    assert all(int(bp) <= 900 for bp in hiding), f"suspicious breakpoint: {hiding}"


def test_empty_state_rows_survive_card_conversion(app, client):
    """The colspan empty-state row must still render on a fresh DB."""
    with app.app_context():
        db.create_all()
    body = client.get("/fuel/").get_data(as_text=True)
    assert "empty-state" in body
    assert "No fuel logs yet" in body
