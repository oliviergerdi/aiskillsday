from types import SimpleNamespace

import httpx
import yaml
from typer.testing import CliRunner

from nparity import cli, pipeline, store
from nparity.cli import app
from nparity.config import load_seeds


def spec():
    identifier = {"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}
    query = {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["available", "sold"]}}
    return {"openapi": "3.0.0", "paths": {
        "/pets": {"get": {"parameters": [query]}, "post": {"responses": {"201": {"description": "Created"}}}},
        "/pets/{petId}": {"get": {"parameters": [identifier]}, "delete": {"parameters": [identifier]}},
        "/search": {"get": {}},
    }}


def test_seed_command_writes_sources_and_does_not_guess_path_ids(tmp_path):
    schema = spec()
    schema["paths"]["/search"]["get"]["parameters"] = [
        {"name": "q", "in": "query", "schema": {"type": "string", "default": "cats"}},
    ]
    document = tmp_path / "spec.yaml"
    document.write_text(yaml.safe_dump(schema))
    output = tmp_path / "seeds.yaml"
    result = CliRunner().invoke(app, ["seeds", str(document), "--out", str(output)])
    assert result.exit_code == 0, result.output
    seeds = load_seeds(output)
    assert seeds.operations["GET /pets"].params["status"][0].source == "enum"
    assert seeds.operations["GET /search"].params["q"][0].value == "cats"
    assert "GET /pets/{petId}" not in seeds.operations


def test_contract_compares_mutations_without_calling_them_and_marks_unseeded_endpoints():
    old, new = spec(), spec()
    new["paths"]["/pets"]["post"]["responses"] = {"202": {"description": "Accepted"}}
    del new["paths"]["/pets/{petId}"]["delete"]
    requests = []

    def serve(request):
        requests.append((request.method, request.url.path))
        return httpx.Response(200, json=[])

    config = pipeline.RunConfig("http://old", "http://new", answer_key=None, seeds=None)
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        run = pipeline.run(config, client, specs=(old, new))

    assert all(method == "GET" for method, _ in requests)
    assert all("/pets/" not in path for _, path in requests)
    coverage = {row.endpoint: row for row in run.coverage}
    assert coverage["GET /pets/{petId}"].reason == "not seeded"
    assert coverage["POST /pets"].reason == "mutating method not enabled"
    assert coverage["POST /pets"].contract_compared
    assert any(change.endpoint == "POST /pets" and change.section == "responses" for change in run.contract)
    assert any(change.endpoint == "DELETE /pets/{petId}" and change.after is None for change in run.contract)


def test_discovered_seed_is_checked_on_new_side_and_matching_404_is_not_coverage():
    routes = spec()
    routes["paths"]["/pets"]["get"]["parameters"][0]["required"] = True
    requests = []

    def serve(request):
        side, path = request.url.host, request.url.path
        requests.append((side, request.method, path, request.url.params.get("status")))
        if path == "/pets":
            return httpx.Response(200, json=[{"id": 42}])
        if path == "/pets/42" and side == "old":
            return httpx.Response(200, json={"id": 42})
        return httpx.Response(404, json={"error": "not found"})

    config = pipeline.RunConfig("http://old", "http://new", answer_key=None, seeds=None,
                                discover_from=["GET /pets", "POST /pets"])
    with httpx.Client(transport=httpx.MockTransport(serve)) as client:
        run = pipeline.run(config, client, specs=(routes, routes))

    coverage = {row.endpoint: row for row in run.coverage}
    assert coverage["GET /pets/{petId}"].seed_sources == ["discovered"]
    assert coverage["GET /pets/{petId}"].reason == "data differs, comparison not valid"
    assert coverage["GET /search"].reason == "both errors"
    assert not [finding for finding in run.findings if finding.endpoint == "GET /pets/{petId}"]
    assert all(method == "GET" for _, method, _, _ in requests)
    assert ("old", "GET", "/pets", "available") in requests


def test_saved_curl_request_supplies_path_id_without_execution(tmp_path):
    spec_path = tmp_path / "spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec()))
    samples = tmp_path / "requests.curl"
    samples.write_text("curl 'https://pets.example/api/pets/42'\n")
    output = tmp_path / "seeds.yaml"
    result = CliRunner().invoke(app, ["seeds", str(spec_path), "--samples", str(samples), "--out", str(output)])
    assert result.exit_code == 0, result.output
    seed = load_seeds(output).operations["GET /pets/{petId}"].params["petId"][0]
    assert (seed.value, seed.source) == (42, "sample")


def test_contract_only_does_not_replay():
    old, new = spec(), spec()
    new["paths"]["/pets"]["post"]["requestBody"] = {"required": True, "content": {
        "application/json": {"schema": {"type": "object", "properties": {"kind": {"enum": ["cat"]}}}},
    }}

    def unexpected(request):
        raise AssertionError(f"Unexpected API call: {request.url}")

    config = pipeline.RunConfig("http://old", "http://new", contract_only=True)
    with httpx.Client(transport=httpx.MockTransport(unexpected)) as client:
        run = pipeline.run(config, client, specs=(old, new))
    assert not run.findings and run.config["requests"] == 0
    assert any(change.endpoint == "POST /pets" and change.section == "request body" for change in run.contract)


def test_cli_reports_basic_checks_from_one_sample_file(tmp_path, monkeypatch):
    sample_file = tmp_path / "samples.yaml"
    sample_file.write_text(yaml.safe_dump({"requests": [{
        "old": {"method": "GET", "path": "/cats/42"},
        "new": {"method": "GET", "path": "/pets/42"},
    }]}))
    requests = []

    def serve(request):
        requests.append((request.method, request.url.path))
        if request.url.host == "before":
            return httpx.Response(200, json={"name": "Cat", "id": 42})
        return httpx.Response(201, json={"name": "Other", "id": "42"})

    def local_client(**kwargs):
        return httpx.Client(transport=httpx.MockTransport(serve), **kwargs)

    monkeypatch.setattr(cli, "httpx", SimpleNamespace(Client=local_client))
    result = CliRunner().invoke(app, ["run", "--old", "http://before", "--new", "http://after",
                                     "--samples", str(sample_file), "--runs-dir", str(tmp_path / "runs")])
    assert result.exit_code == 0, result.output
    assert "No API spec: basic checks only. 1 of 1 endpoints compared. This is not a full comparison." in result.output
    assert requests == [("GET", "/cats/42"), ("GET", "/pets/42")]
    run, = store.list_runs(tmp_path / "runs")
    assert {finding.path for finding in run.findings} == {"$.id", "status"}
    assert not run.contract and not run.coverage[0].contract_compared
