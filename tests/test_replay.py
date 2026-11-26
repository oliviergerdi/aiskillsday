import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity.models import EndpointMap, Request
from nparity.replay import fill, replay, to_new
from nparity.retry import RetryPolicy

FAST = RetryPolicy(base=0.0)
OLD, NEW = "http://testserver/v1", "http://testserver/v2"

EMAP = {
    "GET /customers/{id}": EndpointMap(old="GET /customers/{id}", new="GET /clients/{clientId}",
                                       source="llm", p=1.0, status="accepted"),
    "GET /orders/{id}": EndpointMap(old="GET /orders/{id}", new="GET /orders/{id}", source="rule", status="accepted"),
    "GET /orders": EndpointMap(old="GET /orders", new="GET /orders", source="rule", status="accepted"),
}


def r(method, path, **params):
    return Request(method=method, path=path, params=params)


def test_fill_and_to_new():
    req = r("GET", "/customers/{id}", id=2)
    assert fill(req) == ("/customers/2", {})
    assert fill(r("GET", "/orders", page=2)) == ("/orders", {"page": 2})
    new = to_new(req, EMAP["GET /customers/{id}"])
    assert (new.path, new.params) == ("/clients/{clientId}", {"clientId": 2})


@pytest.fixture(scope="module")
def tc():
    return TestClient(app)


def test_replay_against_toys(tc):
    reqs = [r("GET", "/customers/{id}", id=2), r("GET", "/orders/{id}", id=999), r("GET", "/orders", page=2),
            r("GET", "/unmapped/{id}", id=1)]
    samples, retries = replay(reqs, EMAP, tc, OLD, NEW, FAST, workers=1)
    cust, missing, page2, unmapped = samples
    assert cust.new_request.path == "/clients/{clientId}"
    assert cust.old.body["fullName"] == cust.new.body["name"]
    assert (missing.old.status, missing.new.status) == (404, 404)          # results, not errors
    assert missing.old.error is None and missing.new.error is None
    assert page2.new.body["items"] == []
    assert unmapped.new_request is None and unmapped.new.error == "unmapped"
    assert retries == 0


def test_transport_failure_is_isolated():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.startswith("/v2/orders/1"):
            raise httpx.ConnectError("connection reset")
        return httpx.Response(200, json={"ok": request.url.path})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    reqs = [r("GET", "/orders/{id}", id=1), r("GET", "/orders/{id}", id=2)]
    samples, retries = replay(reqs, EMAP, client, "http://h/v1", "http://h/v2", FAST, workers=2)
    assert samples[0].new.status is None and "after 4 attempts" in samples[0].new.error
    assert samples[1].new.status == 200 and samples[1].old.status == 200
    assert retries == 3


def test_retryable_status_then_success():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(503) if calls["n"] == 1 else httpx.Response(200, json={"a": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    samples, retries = replay([r("GET", "/orders", page=1)], EMAP, client, "http://h/v1", "http://h/v2", FAST, workers=1)
    assert samples[0].old.status == 200 and retries == 1
