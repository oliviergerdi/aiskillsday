from datetime import UTC, datetime, timedelta

from nparity import store
from nparity.models import EndpointMap, Finding, HttpResult, Request, Run, Sample


def _run(run_id: str, started: datetime) -> Run:
    req = Request(method="GET", path="/orders/{id}", params={"id": 2})
    sample = Sample(
        old_request=req,
        new_request=req,
        old=HttpResult(status=200, body={"total": 10.01, "raw": 10.005}),
        new=HttpResult(status=200, body={"total": 10.0, "raw": 10.005}),
    )
    return Run(
        id=run_id,
        started_at=started,
        endpoints=[EndpointMap(old="GET /orders/{id}", new="GET /orders/{id}", source="llm",
                               p=0.99, status="accepted", top3=[("GET /orders/{id}", 0.99)])],
        findings=[Finding(id="f-001", endpoint="GET /orders/{id}", path="$.total", kind="changed",
                          source="diff", samples=[sample], differing=1)],
    )


def test_round_trip_keeps_floats(tmp_path):
    run = _run("r1", datetime(2026, 11, 26, 9, 0, tzinfo=UTC))
    store.save(run, tmp_path)
    loaded = store.load("r1", tmp_path)
    assert loaded == run
    body_old = loaded.findings[0].samples[0].old.body
    body_new = loaded.findings[0].samples[0].new.body
    assert body_old["total"] == 10.01
    assert body_new["total"] == 10.0
    assert body_old["raw"] == 10.005
    assert isinstance(body_new["total"], float)


def test_list_runs_newest_first(tmp_path):
    t0 = datetime(2026, 11, 26, 9, 0, tzinfo=UTC)
    store.save(_run("older", t0), tmp_path)
    store.save(_run("newer", t0 + timedelta(hours=1)), tmp_path)
    assert [r.id for r in store.list_runs(tmp_path)] == ["newer", "older"]


def test_list_runs_missing_dir(tmp_path):
    assert store.list_runs(tmp_path / "nope") == []
