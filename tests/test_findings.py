"""Findings on the real toy services, mapped with FakeBackend (answer-key items 1-10)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from nparity.config import load_noise, load_seeds, load_thresholds
from nparity.evaluator.fake import FakeBackend
from nparity.findings import build_findings
from nparity.generate import generate
from nparity.map import map_endpoints, map_fields
from nparity.openapi import endpoints, load_spec
from nparity.replay import replay
from nparity.retry import RetryPolicy

OLD, NEW = "http://testserver/v1", "http://testserver/v2"


@pytest.fixture(scope="module")
def built():
    c = TestClient(app)
    v1, v2 = endpoints(load_spec(c, OLD)), endpoints(load_spec(c, NEW))
    ev, th = FakeBackend.from_file("fixtures/answer_key.yaml"), load_thresholds()
    emap = map_endpoints(v1, v2, ev, th)
    by_key = {e.key: e for e in v2}
    pairs = [(o, by_key[m.new]) for o, m in zip(v1, emap) if m.new]
    fmap = map_fields(pairs, ev, th)
    samples, _ = replay(generate(v1, load_seeds("fixtures/seeds.yaml")), {m.old: m for m in emap},
                        c, OLD, NEW, RetryPolicy(base=0.0), workers=1)
    return build_findings(emap, fmap, samples, load_noise("config/noise.yaml"), v1, v2)


def keyed(findings):
    return {(f.endpoint, f.path): f for f in findings}


def test_findings_are_answer_key_items_3_to_10(built):
    findings, noise, errors = built
    assert errors == []
    assert set(keyed(findings)) == {
        ("POST /orders", "status"),                   # 3
        ("GET /customers/{id}", "$.fullName"),        # 4
        ("GET /customers/{id}", "$.legacyCode"),      # 5
        ("GET /orders/{id}", "$.total"),              # 6
        ("GET /orders", "$.items"),                   # 7
        ("GET /customers/{id}", "$.currency"),        # 8
        ("GET /orders/{id}", "$.detail"),             # 9
        ("GET /customers/{id}", "endpoint"),          # 10
    }
    assert {(x.endpoint, x.path) for x in noise} == {
        ("GET /orders", "$.items"), ("POST /orders", "$.id"), ("POST /orders", "$.createdAt")}


def test_kinds_and_counts(built):
    f = keyed(built[0])
    assert f[("GET /orders/{id}", "$.total")].kind == "changed"
    assert f[("GET /orders/{id}", "$.total")].differing == 1
    assert len(f[("GET /orders/{id}", "$.total")].samples) == 3
    assert f[("GET /orders", "$.items")].kind == "items_removed"        # PRD 0002: keyed lists match by id
    assert f[("GET /customers/{id}", "$.currency")].kind == "missing_in_new"
    assert f[("GET /customers/{id}", "endpoint")].kind == "moved"
    assert f[("GET /customers/{id}", "endpoint")].new_endpoint == "GET /clients/{clientId}"
    assert f[("POST /orders", "status")].kind == "status_changed"
    assert [x.id for x in built[0]] == [f"f-{n:03d}" for n in range(1, 9)]


def test_rename_once_not_as_value_diff(built):
    """Review focus 1: the rename vanishes from the value diff and appears once as `renamed`."""
    findings = built[0]
    on_name = [f for f in findings if f.path in ("$.fullName", "$.name")]
    assert [(f.kind, f.source) for f in on_name] == [("renamed", "mapping")]
    assert [f.kind for f in findings if f.path == "$.legacyCode"] == ["dropped"]


def test_sorting_does_not_hide_empty_page(built):
    """Review focus 2: noise rule sorts $.items, page 2 still shows up empty."""
    f = keyed(built[0])[("GET /orders", "$.items")]
    assert f.differing == 1
    page2 = f.samples[f.differs_in[0]]
    assert page2.old_request.params == {"page": 2}
    assert page2.new.body["items"] == []


def test_declared_type_attached_to_currency(built):
    f = keyed(built[0])[("GET /customers/{id}", "$.currency")]
    assert f.type_info["declared"] == "string, required → string | null, optional"
    assert "observed" in f.type_info
    assert not [x for x in built[0] if x.kind == "declared_type_changed"]
