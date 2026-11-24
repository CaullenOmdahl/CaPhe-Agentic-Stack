"""Split a list into pages. Pages are 1-based."""


def paginate(items, page, per_page):
    """Return {"items": [...], "page": page, "total_pages": n}.

    Raises ValueError for page < 1 or per_page < 1. A page beyond the end
    returns an empty "items" list.
    """
    if page < 1 or per_page < 1:
        raise ValueError("page and per_page must be >= 1")
    total_pages = len(items) // per_page
    start = page * per_page
    return {"items": list(items[start:start + per_page]), "page": page, "total_pages": total_pages}
