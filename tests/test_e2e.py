"""Walking skeleton: the whole pipeline on the toy services with FakeBackend."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity import pipeline
from nparity.retry import RetryPolicy

OLD, NEW = "http://testserver/v1", "http://testserver/v2"


def cfg(**kw):
    return pipeline.RunConfig(old=OLD, new=NEW, workers=1, retry=RetryPolicy(base=0.0), **kw)


@pytest.fixture(scope="module")
def result():
    return pipeline.run(cfg(), TestClient(app))


def test_scores_ten_out_of_ten(result):
    s = result.score
    assert (s.correct, s.total, s.false_regressions) == (10, 10, 0), [d for d in s.details if not d["ok"]]


def test_shape(result):
    shown = {(f.endpoint, f.path) for f in result.findings if f.status == "shown"}
    assert shown == {("GET /orders/{id}", "$.total"), ("GET /orders", "$.items"), ("GET /customers/{id}", "$.currency")}
    assert [(f.endpoint, f.path) for f in result.findings if f.status == "unsure"] == [("GET /orders/{id}", "$.detail")]
    assert sum(f.status == "accepted" for f in result.findings) == 4
    assert result.errors == []
    t = result.telemetry
    assert t.rule_decisions > t.llm_calls > 0
    assert result.config["backend"] == "fake"


class DropsOrder1(TestClient):
    def request(self, method, url, *args, **kwargs):
        if str(url).endswith("/v2/orders/1"):
            raise httpx.ConnectError("connection reset by peer")
        return super().request(method, url, *args, **kwargs)


def test_one_failing_request_does_not_kill_the_run():
    """Review focus 5."""
    r = pipeline.run(cfg(), DropsOrder1(app))
    assert len(r.errors) == 1 and r.errors[0].status == "error"
    assert "GET /orders/{id}" == r.errors[0].endpoint
    assert r.telemetry.retries == 3
    assert r.score.correct == 10
