"""Hits Fireworks. Skipped unless FIREWORKS_API_KEY is set: poetry run pytest -m live -v -s"""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity import pipeline
from nparity.evaluator.base import Choice
from nparity.evaluator.cache import Cached
from nparity.evaluator.logprob_chat import LogprobChatBackend
from nparity.retry import RetryPolicy

pytestmark = [pytest.mark.live,
              pytest.mark.skipif(not os.environ.get("FIREWORKS_API_KEY"), reason="FIREWORKS_API_KEY not set")]


@pytest.fixture(scope="module")
def flash():
    return LogprobChatBackend.from_profile("config/profiles/flash.yaml")


def test_mapping_question(flash):
    q = Choice(id="m", instructions=("Old endpoint: GET /customers/{id} returns { id, fullName, email, type, "
                                     "currency, legacyCode }. A rewrite may rename paths, resources and fields. "
                                     "Which new endpoint is the best match for it?"),
               criteria={"GET /orders": "GET /orders returns { page, items }",
                         "GET /orders/{id}": "GET /orders/{id} returns { id, customerId, items, total, currency, status }",
                         "GET /clients/{clientId}": "GET /clients/{clientId} returns { id, name, email, type, currency }",
                         "none": "None of these: the old endpoint has no counterpart"})
    a = flash.evaluate({"old_endpoint": "GET /customers/{id}"}, [q], reasons=True)["m"]
    print(a.model_dump())
    assert a.value == "GET /clients/{clientId}" and a.p_winner > 0.95
    assert a.reason


def test_full_pipeline_on_toys(flash, tmp_path):
    ev = Cached(flash, tmp_path)
    r = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                        retry=RetryPolicy(base=0.0)), TestClient(app), ev=ev)
    for d in r.score.details:
        print(d)
    for f in r.findings:
        print(f"{f.id} {f.endpoint} {f.path} {f.kind} -> {f.label}/{f.status} p={f.p} "
              f"{ {k: round(v, 3) for k, v in f.probabilities.items()} } | {f.reason}")
    print(r.telemetry)
    got = {d["n"]: d["got"] for d in r.score.details}
    assert got[6] == "regression"
    assert got[3] in ("intended", "unsure")
    assert r.score.false_regressions == 0
