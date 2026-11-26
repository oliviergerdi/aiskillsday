"""One test per seeded difference (answer key numbering), plus the OpenAPI specs."""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def c():
    return TestClient(app)


BODY = {"customerId": 1, "items": [{"sku": "A1", "qty": 2, "unit": 5.0}]}


def test_1_order_list_differs_in_order_only(c):
    old = c.get("/v1/orders", params={"page": 1}).json()["items"]
    new = c.get("/v2/orders", params={"page": 1}).json()["items"]
    assert [o["id"] for o in old] == [1, 2, 3]
    assert [o["id"] for o in new] == [3, 2, 1]
    assert sorted(new, key=lambda o: o["id"]) == old


def test_2_created_ids_and_timestamps_differ(c):
    a = c.post("/v1/orders", json=BODY).json()
    b = c.post("/v2/orders", json=BODY).json()
    assert a["id"].startswith("ord_") and b["id"].startswith("ord_")
    assert a["id"] != b["id"]
    for k in ("customerId", "items", "total", "currency", "status"):
        assert a[k] == b[k], k


def test_3_create_returns_201_in_v2(c):
    assert c.post("/v1/orders", json=BODY).status_code == 200
    assert c.post("/v2/orders", json=BODY).status_code == 201


def test_4_5_10_customer_moved_renamed_and_legacy_dropped(c):
    old = c.get("/v1/customers/1").json()
    new = c.get("/v2/clients/1").json()
    assert old["fullName"] == new["name"] == "Ada Mokoena"
    assert "fullName" not in new
    assert old["legacyCode"] == "L-001" and "legacyCode" not in new
    assert c.get("/v2/customers/1").status_code == 404


def test_6_total_rounding(c):
    assert c.get("/v1/orders/2").json()["total"] == 10.01
    assert c.get("/v2/orders/2").json()["total"] == 10.0
    for oid in (1, 3, 4, 5):
        assert c.get(f"/v1/orders/{oid}").json() == c.get(f"/v2/orders/{oid}").json(), oid


def test_7_last_page_empty_in_v2(c):
    assert [o["id"] for o in c.get("/v1/orders", params={"page": 2}).json()["items"]] == [4, 5]
    assert c.get("/v2/orders", params={"page": 2}).json()["items"] == []


def test_8_currency_missing_for_business(c):
    assert c.get("/v1/customers/2").json()["currency"] == "ZAR"
    assert "currency" not in c.get("/v2/clients/2").json()
    assert c.get("/v2/clients/1").json()["currency"] == "ZAR"


def test_9_not_found_wording(c):
    old = c.get("/v1/orders/999")
    new = c.get("/v2/orders/999")
    assert old.status_code == new.status_code == 404
    assert old.json() == {"detail": "Order not found"}
    assert new.json() == {"detail": "No order with id 999"}


def test_customer_not_found_identical(c):
    assert c.get("/v1/customers/999").json() == c.get("/v2/clients/999").json()


def test_openapi_specs(c):
    v1 = c.get("/v1/openapi.json")
    v2 = c.get("/v2/openapi.json")
    assert v1.status_code == v2.status_code == 200
    assert set(v1.json()["paths"]) == {"/orders", "/orders/{id}", "/customers/{id}"}
    assert set(v2.json()["paths"]) == {"/orders", "/orders/{id}", "/clients/{clientId}"}
    client_schema = v2.json()["components"]["schemas"]["Client"]
    assert "currency" not in client_schema.get("required", [])
    assert "currency" in v1.json()["components"]["schemas"]["Customer"]["required"]
