"""In-memory data shared by the toy v1 and v2 services.

Seeded so every difference in the answer key is reachable from fixtures/seeds.yaml:
- order 2 totals 10.005 (3 x 3.335): v1 rounds half-up to 10.01, v2's float round gives 10.0
- 5 orders at page size 3: v1 has 2 pages, v2's floor division has 1
- customer 2 is a business: v2 drops its currency
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

PAGE_SIZE = 3
CURRENCY = "ZAR"

CUSTOMERS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "fullName": "Ada Mokoena", "email": "ada@example.com", "type": "person",
        "currency": CURRENCY, "legacyCode": "L-001"},
    2: {"id": 2, "fullName": "Brightwater Holdings", "email": "ops@brightwater.example", "type": "business",
        "currency": CURRENCY, "legacyCode": "L-002"},
}

ORDERS: dict[int, dict[str, Any]] = {
    1: {"id": 1, "customerId": 1, "status": "paid", "items": [{"sku": "A1", "qty": 2, "unit": 5.0}]},
    2: {"id": 2, "customerId": 2, "status": "paid", "items": [{"sku": "B2", "qty": 3, "unit": 3.335}]},
    3: {"id": 3, "customerId": 1, "status": "shipped",
        "items": [{"sku": "C3", "qty": 1, "unit": 19.99}, {"sku": "A1", "qty": 1, "unit": 5.0}]},
    4: {"id": 4, "customerId": 2, "status": "pending", "items": [{"sku": "D4", "qty": 4, "unit": 2.5}]},
    5: {"id": 5, "customerId": 1, "status": "paid", "items": [{"sku": "E5", "qty": 2, "unit": 7.125}]},
}


def total_v1(items: list[dict[str, Any]]) -> float:
    """Correct: decimal arithmetic, half-up to cents."""
    total = sum((Decimal(str(i["unit"])) * i["qty"] for i in items), Decimal("0"))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def total_v2(items: list[dict[str, Any]]) -> float:
    """The seeded bug: float arithmetic + round(), so 10.005 becomes 10.0."""
    return round(sum(i["qty"] * i["unit"] for i in items), 2)


def summary(order: dict[str, Any]) -> dict[str, Any]:
    return {"id": order["id"], "customerId": order["customerId"], "status": order["status"]}


def sorted_orders() -> list[dict[str, Any]]:
    return [ORDERS[k] for k in sorted(ORDERS)]
