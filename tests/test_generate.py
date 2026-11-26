import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity.config import Seeds, load_seeds
from nparity.generate import generate
from nparity.openapi import endpoints, load_spec


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture(scope="module")
def v1(client):
    return endpoints(load_spec(client, "http://testserver/v1"))


@pytest.fixture(scope="module")
def v2(client):
    return endpoints(load_spec(client, "http://testserver/v2"))


def by_key(eps):
    return {e.key: e for e in eps}


def test_v1_endpoints(v1):
    eps = by_key(v1)
    assert set(eps) == {"GET /orders", "POST /orders", "GET /orders/{id}", "GET /customers/{id}"}
    assert eps["GET /orders/{id}"].path_params == ["id"]
    assert eps["GET /orders"].query_params == ["page"]
    assert eps["GET /orders"].required == set()
    assert eps["POST /orders"].has_body
    props = eps["GET /orders/{id}"].response_schema["properties"]
    assert props["total"]["type"] == "number"
    # $ref inside a list resolved
    assert eps["GET /orders"].response_schema["properties"]["items"]["items"]["properties"]["status"]["type"] == "string"


def test_v2_declared_optional_currency(v2):
    schema = by_key(v2)["GET /clients/{clientId}"].response_schema
    assert "currency" not in schema.get("required", [])
    assert {"type": "null"} in schema["properties"]["currency"]["anyOf"]


def test_generate_from_fixture_seeds(v1):
    reqs = generate(v1, load_seeds("fixtures/seeds.yaml"))
    by = {}
    for r in reqs:
        by.setdefault(r.endpoint, []).append(r)
    assert [r.params for r in by["GET /orders/{id}"]] == [{"id": 1}, {"id": 2}, {"id": 999}]
    assert [r.params for r in by["GET /customers/{id}"]] == [{"id": 1}, {"id": 2}, {"id": 999}]
    assert [r.params for r in by["GET /orders"]] == [{"page": 1}, {"page": 2}]
    assert [r.body["customerId"] for r in by["POST /orders"]] == [1, 2]
    assert all(1 <= len(v) <= 5 for v in by.values())
    assert set(by) == {"GET /orders", "POST /orders", "GET /orders/{id}", "GET /customers/{id}"}


def test_cap(v1):
    reqs = generate(v1, Seeds(params={"id": list(range(10))}), cap=5)
    assert len([r for r in reqs if r.endpoint == "GET /orders/{id}"]) == 5


def test_missing_required_seed_skips_endpoint(v1):
    reqs = generate(v1, Seeds(params={"page": [1]}))
    assert {r.endpoint for r in reqs} == {"GET /orders"}


def test_optional_query_without_seed_is_left_out(v1):
    reqs = generate(v1, Seeds(params={"id": [1]}))
    assert [r.params for r in reqs if r.endpoint == "GET /orders"] == [{}]
