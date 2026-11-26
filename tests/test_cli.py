import json
import time

import httpx
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.main import app
from nparity import cli as cli_module, pipeline, store
from nparity.cli import app as cli
from nparity.retry import RetryPolicy


def test_show_and_runs(tmp_path):
    r = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                        retry=RetryPolicy(base=0.0)), TestClient(app))
    store.save(r, tmp_path)
    runner = CliRunner()
    out = runner.invoke(cli, ["show", r.id, "--runs-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    assert "Regressions: 3" in out.output
    assert "Answer key: 10/10 correct" in out.output
    listed = runner.invoke(cli, ["runs", "--runs-dir", str(tmp_path)])
    assert r.id in listed.output


def test_freeze(tmp_path):
    r = pipeline.run(pipeline.RunConfig(old="http://testserver/v1", new="http://testserver/v2", workers=1,
                                        retry=RetryPolicy(base=0.0)), TestClient(app))
    store.save(r, tmp_path)
    out = CliRunner().invoke(cli, ["freeze", r.id, "--runs-dir", str(tmp_path)])
    assert out.exit_code == 0, out.output
    demo = store.load("demo", tmp_path)
    assert demo.id == "demo" and demo.score.correct == 10


def test_json_run_show_list_and_freeze(tmp_path):
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps({"openapi": "3.0.0", "paths": {"/pets": {"get": {}}}}), encoding="utf-8")
    runner = CliRunner()

    result = runner.invoke(cli, ["run", "--format", "json", "--old", "http://before", "--new", "http://after",
                                 "--old-spec", str(spec), "--new-spec", str(spec), "--contract-only",
                                 "--runs-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    run = json.loads(result.stdout)
    assert run["coverage"][0]["endpoint"] == "GET /pets"
    assert run["report_url"].endswith(f"/runs/{run['id']}")
    assert store.load(run["id"], tmp_path).id == run["id"]

    shown = runner.invoke(cli, ["--format", "json", "show", run["id"], "--runs-dir", str(tmp_path)])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout) == run

    listed = runner.invoke(cli, ["runs", "--format", "json", "--runs-dir", str(tmp_path)])
    assert listed.exit_code == 0, listed.output
    assert [entry["id"] for entry in json.loads(listed.stdout)] == [run["id"]]

    frozen = runner.invoke(cli, ["freeze", run["id"], "--format", "json", "--runs-dir", str(tmp_path)])
    assert frozen.exit_code == 0, frozen.output
    assert json.loads(frozen.stdout)["id"] == "demo"


def test_json_seeds_reports_generated_values(tmp_path):
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps({"paths": {"/pets": {"get": {"parameters": [
        {"name": "page", "in": "query", "schema": {"type": "integer", "default": 1}}
    ]}}}}), encoding="utf-8")
    output = tmp_path / "seeds.yaml"
    result = CliRunner().invoke(cli, ["seeds", str(spec), "--out", str(output), "--format", "json"])
    assert result.exit_code == 0, result.output
    generated = json.loads(result.stdout)
    assert generated["seeds"]["operations"]["GET /pets"]["params"]["page"] == [{"value": 1, "source": "default"}]
    assert generated["saved_to"] == str(output) and output.is_file()


def test_agent_usage_errors_are_json_on_stderr():
    result = CliRunner().invoke(cli, ["run", "--format", "json"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert json.loads(result.stderr)["error"]["code"] == "invalid_input"


def test_dry_run_does_not_replay_or_save(tmp_path):
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({"paths": {"/pets": {"get": {}}, "/pets/{id}": {"get": {"parameters": [
        {"in": "path", "name": "id", "required": True, "schema": {"type": "integer"}}
    ]}}}}), encoding="utf-8")
    result = CliRunner().invoke(cli, ["run", "--format", "json", "--dry-run", "--backend", "flash",
                                     "--old", "http://unreachable.invalid", "--new", "http://unreachable.invalid",
                                     "--old-spec", str(spec), "--new-spec", str(spec), "--runs-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    plan = json.loads(result.stdout)
    assert plan["dry_run"] is True
    assert plan["requests"] == 1
    rows = {row["endpoint"]: row for row in plan["endpoints"]}
    assert rows["GET /pets/{id}"]["reason"] == "not seeded"
    assert not list(tmp_path.glob("*.yaml"))


def test_compact_results_link_to_full_finding(tmp_path):
    run = pipeline.run(pipeline.RunConfig("http://testserver/v1", "http://testserver/v2"), TestClient(app))
    store.save(run, tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["show", run.id, "--format", "json", "--compact", "--status", "regression",
                                 "--limit", "1", "--runs-dir", str(tmp_path)])
    assert result.exit_code == 0, result.output
    compact = json.loads(result.stdout)
    finding, = compact["findings"]
    assert compact["counts"]["regressions"] == 3
    assert "samples" not in finding
    detail = runner.invoke(cli, ["finding", run.id, finding["key"], "--format", "json", "--runs-dir", str(tmp_path)])
    assert detail.exit_code == 0, detail.output
    assert json.loads(detail.stdout)["finding"]["samples"]


def test_gate_leaves_a_report_and_progress_can_be_resumed(tmp_path, monkeypatch):
    run = pipeline.run(pipeline.RunConfig("http://testserver/v1", "http://testserver/v2"), TestClient(app))

    def fixed_run(cfg, client, progress):
        progress("Replaying requests")
        return run.model_copy(update={"id": cfg.run_id})

    monkeypatch.setattr(cli_module.pipeline, "run", fixed_run)
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--format", "json", "--compact", "--old", "http://before", "--new", "http://after",
                                 "--fail-on", "regression", "--progress", "jsonl", "--runs-dir", str(tmp_path)])
    assert result.exit_code == 5, result.output
    payload = json.loads(result.stdout)
    events = [json.loads(line) for line in result.stderr.splitlines()]
    assert all(event["run_id"] == payload["id"] for event in events[:-1])
    assert events[-1]["error"]["code"] == "gate_failed"
    assert store.load(payload["id"], tmp_path).id == payload["id"]

    polled = runner.invoke(cli, ["status", payload["id"], "--after", "2", "--format", "json", "--runs-dir", str(tmp_path)])
    assert polled.exit_code == 0, polled.output
    state = json.loads(polled.stdout)
    assert state["state"] == "complete" and state["exit_code"] == 5
    assert state["events"] == events[2:-1]


def test_detached_run_can_be_polled_in_later_cli_invocations(tmp_path):
    spec = tmp_path / "openapi.json"
    spec.write_text(json.dumps({"paths": {"/pets": {"get": {}}}}), encoding="utf-8")
    runner = CliRunner()
    queued = runner.invoke(cli, ["run", "--format", "json", "--detach", "--old", "http://before", "--new", "http://after",
                                 "--old-spec", str(spec), "--new-spec", str(spec), "--contract-only",
                                 "--runs-dir", str(tmp_path)])
    assert queued.exit_code == 0, queued.output
    first = json.loads(queued.stdout)
    assert first["state"] == "queued"
    after = first["events"][-1]["seq"]
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        polled = runner.invoke(cli, ["status", first["run_id"], "--after", str(after), "--wait", "1",
                                     "--format", "json", "--runs-dir", str(tmp_path)])
        assert polled.exit_code == 0, polled.output
        state = json.loads(polled.stdout)
        if state["events"]:
            after = state["events"][-1]["seq"]
        if state["state"] in ["complete", "failed"]:
            break
    assert state["state"] == "complete" and state["exit_code"] == 0, state
    assert state["report_url"].endswith(first["run_id"])
    assert store.load(first["run_id"], tmp_path).id == first["run_id"]


def test_transport_errors_are_retryable_json_without_url_secrets(monkeypatch):
    def unavailable(cfg, client, progress):
        raise httpx.ConnectError("upstream URL contains a secret")

    monkeypatch.setattr(cli_module.pipeline, "run", unavailable)
    result = CliRunner().invoke(cli, ["run", "--format", "json", "--old", "http://before", "--new", "http://after"])
    assert result.exit_code == 3 and result.stdout == ""
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "transport_error" and error["retryable"] is True
    assert "secret" not in result.stderr
