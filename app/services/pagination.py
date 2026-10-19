"""Shared query pagination helper. Must not import Flask."""
from math import ceil


def paginate(query, page: int = 1, per_page: int = 15) -> tuple[list, int, int]:
    """Return (items, total, pages). Clamps page into [1, max(pages,1)]."""
    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = 15
    if per_page <= 0:
        per_page = 15

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1

    total = query.count()
    pages = max(ceil(total / per_page), 1)
    page = max(1, min(page, pages))
    items = query.offset((page - 1) * per_page).limit(per_page).all()
    return items, total, pages
