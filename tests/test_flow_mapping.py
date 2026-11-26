import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from app.main import app
from app.web.configs import RunInput
from app.web.run_jobs import compare
from nparity import pipeline, store
from nparity.cli import app as cli
from nparity.config import load_thresholds
from nparity.evaluator.base import one_hot
from nparity.flow import candidates, map_flows, operations, ordered_steps, verify_source
from nparity.flow_score import score_flows
from nparity.evaluator.fake import FakeBackend
from nparity.models import AnswerKey, FlowCitation, FlowKey, FlowMap, FlowMapping, FlowStep, Run, Telemetry


def toy_specs():
    client = TestClient(app)
    return tuple(client.get(f"/flow/v{version}/openapi.json").raise_for_status().json() for version in (1, 2))


def test_flow_mapping_from_specs_never_replays_operations():
    before, after = toy_specs()
    old_ops, new_ops = operations(before), operations(after)
    (screen,) = [op for op in old_ops if op.key == "POST /screenings"]
    assert {op.key for op in candidates(screen, new_ops)} >= {
        "POST /token", "GET /screening-configurations", "POST /screening-jobs",
        "callback screeningCompleted (POST /screening-jobs)", "GET /screening-results/{resultId}",
    }
    health = next(op for op in old_ops if op.key == "GET /health")
    assert [op.key for op in candidates(health, new_ops)] == ["GET /health"]

    def unexpected(request):
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    cfg = pipeline.RunConfig("http://before", "http://after", flow_mapping=True, intent=None)
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        run = pipeline.run(cfg, client, specs=(before, after))
    result = run.flow_mapping
    screening = next(flow for flow in result.flows if flow.old_op == screen.key)
    assert [(step.new_op, step.role) for step in screening.steps] == [
        ("POST /token", "auth"),
        ("GET /screening-configurations", "configure"),
        ("POST /screening-jobs", "start"),
        ("callback screeningCompleted (POST /screening-jobs)", "await"),
        ("GET /screening-results/{resultId}", "read"),
        ("GET /screening-results/{resultId}/pages/{pageId}", "page"),
    ]
    assert all(step.status == "suggested" and step.source.quote for step in screening.steps)
    assert screening.status == "needs_review"
    assert result.unmatched_old == ["GET /legacy-screening-statistics"]
    assert result.unmatched_new == ["GET /service-metrics"]
    assert next(flow for flow in result.flows if flow.old_op == "GET /health").steps[0].role == "direct"
    assert Run.model_validate_json(run.model_dump_json()) == run


def test_flow_citation_requires_verbatim_source_text():
    _, spec = toy_specs()
    token = next(op for op in operations(spec) if op.key == "POST /token")
    quote = token.source
    assert verify_source(quote, token) == quote
    assert verify_source(FlowCitation(reference=quote.reference, quote="a made-up sentence"), token) is None


def test_candidate_classified_none_is_counted_and_left_unmatched():
    spec = {"paths": {"/health": {"get": {"summary": "Health"}}}}
    ev = FakeBackend(AnswerKey(), flow_key=FlowKey(unmatched_old=["GET /health"]))
    result = map_flows(spec, spec, ev, load_thresholds(), Telemetry())
    assert result.none_count == 1
    assert result.flows == []
    assert result.unmatched_old == result.unmatched_new == ["GET /health"]


def test_order_is_stable_for_shuffled_steps():
    a, b, c = [FlowStep(new_op=op, role="read", p=1, status="suggested") for op in ("B", "A", "C")]
    edges = {"A": {"B"}, "B": set(), "C": {"A"}}
    assert ordered_steps([c, b, a], edges) == ordered_steps([a, c, b], edges) == ([a, b, c], None)


def test_schema_dependencies_and_links_order_openapi_webhooks():
    body = {"type": "object", "required": ["jobId"], "properties": {"jobId": {"type": "string"}}}
    spec = {
        "paths": {
            "/work": {"post": {"responses": {"202": {"content": {"application/json": {"schema": body}}}}}},
            "/work/receipt": {"get": {"operationId": "receipt"}},
        },
        "webhooks": {
            "COMPLETED": {"post": {
                "requestBody": {"content": {"application/json": {"schema": body}}, "required": True},
                "responses": {"204": {"links": {"receipt": {"operationId": "receipt"}}}},
            }},
        },
    }
    edges = {op.key: op.dependencies for op in operations(spec)}
    assert edges == {"POST /work": set(), "webhook COMPLETED": {"POST /work"},
                     "GET /work/receipt": {"webhook COMPLETED"}}


def test_low_probability_and_unverified_quotes_stay_unsure():
    class Evaluator:
        max_options = 8

        def evaluate(self, state, questions):
            (question,) = questions
            answer = one_hot("read", list(question.criteria))
            if state["after"]["operation"] == "GET /screening-configurations":
                answer.p_winner = 0.25
            elif state["after"]["operation"] == "POST /screening-jobs":
                answer.meta["quote"] = "Not in the spec"
            return {question.id: answer}

    before, after = toy_specs()
    result = map_flows(before, after, Evaluator(), load_thresholds(), Telemetry(), workers=1)
    flow = next(flow for flow in result.flows if flow.old_op == "POST /screenings")
    steps = {step.new_op: step for step in flow.steps}
    assert steps["GET /screening-configurations"].status == "unsure"
    bad = steps["POST /screening-jobs"]
    assert bad.status == "unsure" and bad.source is None and "verified" in bad.warning
    assert flow.status == "needs_review"


def test_flow_score_accepts_variant_and_requires_citations():
    key = FlowKey.model_validate({
        "confirmed_by": "test reviewer",
        "flows": [{"old_op": "POST /screen", "variants": [
            {"steps": [{"new_op": "POST /sync", "role": "direct"}]},
            {"steps": [{"new_op": "POST /async", "role": "start"},
                       {"new_op": "webhook COMPLETE", "alt": "GET /job", "role": "await"}]},
        ]}],
        "unmatched_new": [{"op": "GET /health"}],
    })
    source = FlowCitation(reference="#/paths", quote="Screening")
    steps = [
        FlowStep(new_op="POST /async", role="start", p=1, status="suggested", source=source),
        FlowStep(new_op="GET /job", role="await", p=1, status="suggested", source=source),
    ]
    result = FlowMapping(flows=[FlowMap(old_op="POST /screen", steps=steps)], unmatched_new=["GET /health"])
    assert score_flows(result, key).model_dump() == {
        "op_recall": 1, "step_precision": 1, "order_and_roles": 1, "unmatched_old": True, "unmatched_new": True,
    }
    result.flows[0].steps.reverse()
    assert score_flows(result, key).order_and_roles == 0.5
    steps[0].source = None
    assert score_flows(result, key).step_precision == 0.5
    assert score_flows(result, key).op_recall == 0
    with pytest.raises(ValueError, match="confirmed_by"):
        score_flows(result, key.model_copy(update={"confirmed_by": None}))


def test_cli_flow_run_report_and_key(tmp_path):
    before, after = toy_specs()
    locations = [tmp_path / name for name in ("before.json", "after.json")]
    for path, spec in zip(locations, (before, after)):
        path.write_text(json.dumps(spec))
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--flow-mapping", "--name", "flow-test", "--backend", "fake",
                                 "--old-spec", str(locations[0]), "--new-spec", str(locations[1]),
                                 "--contract-only", "--seeds", "missing-seeds.yaml", "--samples", "missing-samples.yaml",
                                 "--seed-samples", "missing-examples.json", "--discover-from", "GET /health",
                                 "--runs-dir", str(tmp_path), "--format", "json"])
    assert result.exit_code == 0, result.output
    saved = json.loads(result.stdout)
    assert saved["config"]["requests"] == 0
    assert saved["flow_mapping"]["unmatched_new"] == ["GET /service-metrics"]
    output = runner.invoke(cli, ["report", saved["id"], "--runs-dir", str(tmp_path)])
    assert output.exit_code == 0, output.output
    assert "POST /screenings" in output.stdout and "No counterpart after" in output.stdout
    assert "Get an access token for screening" in output.stdout
    key = tmp_path / "flow.key.yaml"
    written = runner.invoke(cli, ["key", saved["id"], "--runs-dir", str(tmp_path), "--out", str(key)])
    assert written.exit_code == 0, written.output
    assert "confirmed_by: null" in key.read_text() and "role: await" in key.read_text()


def test_web_flow_mapping_ignores_saved_replay_settings(tmp_path):
    sources = {}
    for side, spec in zip(("before", "after"), toy_specs()):
        path = tmp_path / f"{side}.json"
        path.write_text(json.dumps(spec))
        sources[side] = {"kind": "spec", "source": str(path)}
    inputs = RunInput.model_validate({
        **sources, "flow_mapping": True, "contract_only": True, "seeds": "missing-seeds.yaml",
        "samples": "missing-samples.yaml", "discover_from": ["GET /health"],
    })
    run_id = compare("test-flow", inputs, tmp_path, lambda _: None, configs=tmp_path)
    run = store.load(run_id, tmp_path)
    assert run.config["requests"] == 0
    assert run.flow_mapping.unmatched_new == ["GET /service-metrics"]


def test_web_flow_report_lists_ordered_steps_and_unmatched_operations(tmp_path):
    with httpx.Client() as client:
        cfg = pipeline.RunConfig("http://before", "http://after", flow_mapping=True, run_id="flow-test")
        run = pipeline.run(cfg, client, specs=toy_specs())
    store.save(run, tmp_path)
    previous = app.state.runs_dir
    app.state.runs_dir = tmp_path
    try:
        response = TestClient(app).get("/runs/flow-test")
    finally:
        app.state.runs_dir = previous
    assert response.status_code == 200
    page = response.text
    assert "Flow mapping" in page and "Needs review" in page
    assert page.index("POST /token") < page.index("POST /screening-jobs") < page.index("callback screeningCompleted")
    assert "Get an access token for screening" in page
    assert "No counterpart before" in page and "GET /legacy-screening-statistics" in page
    assert "No counterpart after" in page and "GET /service-metrics" in page
    assert "Ready to cut over" not in page
