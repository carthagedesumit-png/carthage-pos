"""Consistent in-memory pagination for service-returned collections."""

from math import ceil
from typing import Any


def paginate(items: list[Any], page: int, per_page: int) -> dict:
    total = len(items)
    start = (page - 1) * per_page
    return {
        "data": items[start:start + per_page],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": ceil(total / per_page) if total else 0,
        },
    }


def data_response(data: Any) -> dict:
    return {"data": data}
