from app.models import Vehicle
from app.services.pagination import paginate


def _seed(db, count):
    for i in range(count):
        db.session.add(Vehicle(name=f"Vehicle {i}", plate_number=f"GC-P{i}"))
    db.session.commit()


def test_empty_query_returns_zero_zero_one(db):
    items, total, pages = paginate(Vehicle.query, 1, 15)
    assert (items, total, pages) == ([], 0, 1)


def test_total_and_pages_math(db):
    _seed(db, 30)
    items, total, pages = paginate(Vehicle.query, 1, 10)
    assert total == 30
    assert pages == 3
    assert len(items) == 10
    assert items[0].name == "Vehicle 0"


def test_offset_slices_correct_page(db):
    _seed(db, 30)
    page1, _, _ = paginate(Vehicle.query, 1, 10)
    page3, _, _ = paginate(Vehicle.query, 3, 10)
    assert page1[0].name == "Vehicle 0"
    assert page3[0].name == "Vehicle 20"
    assert len(page3) == 10


def test_clamp_below_one(db):
    _seed(db, 5)
    items, total, pages = paginate(Vehicle.query, 0, 15)
    assert len(items) == 5
    assert total == 5
    assert pages == 1


def test_clamp_negative_page(db):
    _seed(db, 5)
    items, _, _ = paginate(Vehicle.query, -7, 15)
    assert len(items) == 5


def test_clamp_above_pages(db):
    _seed(db, 25)
    items, total, pages = paginate(Vehicle.query, 99, 10)
    assert pages == 3
    assert total == 25
    assert len(items) == 5
    assert items[-1].name == "Vehicle 24"


def test_per_page_zero_treated_as_fifteen(db):
    _seed(db, 20)
    items, total, pages = paginate(Vehicle.query, 1, 0)
    assert len(items) == 15
    assert pages == 2
    assert total == 20


def test_per_page_negative_treated_as_fifteen(db):
    _seed(db, 20)
    items, _, pages = paginate(Vehicle.query, 1, -3)
    assert len(items) == 15
    assert pages == 2


def test_partial_last_page(db):
    _seed(db, 17)
    items, total, pages = paginate(Vehicle.query, 2, 15)
    assert pages == 2
    assert total == 17
    assert len(items) == 2
