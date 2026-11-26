import json
from pathlib import Path

import httpx

from nparity import contract, pipeline
from nparity.evaluator.base import one_hot
from nparity.evaluator.fake import FakeBackend
from nparity.models import AnswerKey
from nparity.openapi import endpoints
from nparity.review import Ledger, scope_of, verdict
from nparity.triage import intent_declares_independent_data


def test_petstore_contract_ignores_equivalent_parameter_syntax():
    folder = Path("samples/api-versions")
    old, new = [
        endpoints(json.loads((folder / f"petstore_v{version}_spec.json").read_text()))
        for version in (2, 3)
    ]
    changes = contract.compare(old, new, [])
    assert not any(c.endpoint == "GET /pet/{petId}" and c.section == "parameters" for c in changes)
    assert not any(c.endpoint == "GET /pet/findByTags" and c.section == "parameters" for c in changes)
    assert any(c.endpoint == "GET /pet/findByStatus" and c.section == "parameters" for c in changes)
    assert any(c.endpoint == "POST /user/createWithArray" and c.section == "operation" and c.after is None
               for c in changes)


def test_equivalent_swagger_media_wrappers_preserve_the_contract():
    schema = {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}}
    swagger = {"swagger": "2.0", "consumes": ["application/json"], "produces": ["application/json"],
               "paths": {"/items": {"post": {"parameters": [
                   {"in": "body", "name": "body", "required": True, "schema": schema},
               ], "responses": {"201": {"schema": schema}}}}}}
    openapi = {"openapi": "3.0.0", "paths": {"/items": {"post": {
        "requestBody": {"required": True, "content": {"application/json": {"schema": schema}}},
        "responses": {"201": {"content": {"application/json": {"schema": schema}}}},
    }}}}
    assert contract.compare(endpoints(swagger), endpoints(openapi), []) == []


def test_intent_can_establish_shared_test_records_even_with_two_databases():
    assert intent_declares_independent_data("Each API uses its own database.")
    assert not intent_declares_independent_data("We do not use separate databases.")
    assert not intent_declares_independent_data("We use separate databases. Both have identical test records.")


def test_independent_data_ignores_records_but_retains_response_shape_changes(tmp_path):
    pet = {
        "type": "object", "required": ["name"],
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"},
                       "tags": {"type": "array", "items": {"type": "string"}}},
    }
    schemas = {
        "/pets": {"type": "array", "items": pet},
        "/badPets": {"type": "array", "items": pet},
        "/inventory": {"type": "object", "additionalProperties": {"type": "integer"}},
        "/login": {"type": "string"},
    }
    spec = {"paths": {path: {"get": {"responses": {"200": {"content": {"application/json": {"schema": schema}}}}}}
                      for path, schema in schemas.items()}}
    bodies = {
        "/pets": ([{"id": 1, "name": "Cat", "tags": ["old"]}],
                  [{"id": 1, "name": "Dog", "tags": ["new", "extra"]}, {"id": 9, "name": "Other"}]),
        "/badPets": ([{"id": 1, "name": "Cat"}], [{"id": 2, "name": "Dog"}, {"id": 9}]),
        "/inventory": ({"sold": 2, "available": 7}, {"approved": 1}),
        "/login": ({"message": "signed in"}, "signed in"),
    }

    def get(request):
        return httpx.Response(200, json=bodies[request.url.path][request.url.host == "after"])

    intent = tmp_path / "intent.md"
    intent.write_text("The services use separate databases. Records and their values can differ.")
    cfg = pipeline.RunConfig("http://before", "http://after", intent=intent, answer_key=None)
    with httpx.Client(transport=httpx.MockTransport(get)) as client:
        run = pipeline.run(cfg, client, specs=(spec, spec))
    assert [(f.endpoint, f.path, f.status) for f in run.findings] == [
        ("GET /badPets", "$[*].name", "unsure"),
        ("GET /login", "$", "unsure"),
    ]
    assert scope_of(run) != scope_of(run.model_copy(update={"config": {"old": cfg.old, "new": cfg.new}}))
    clean = run.model_copy(update={"findings": []})
    assert verdict(clean, Ledger(path=tmp_path / "ledger.yaml"))[0] != "Ready to cut over"


def test_independent_data_triages_expected_array_item_type_change(tmp_path):
    class IntentEvaluator(FakeBackend):
        def evaluate(self, state, questions, reasons=False):
            if questions[0].id.startswith("triage:"):
                question = questions[0]
                intended = ("Where: response field `$[*].code`" in state
                            and "string → integer" in state and "$[*].code changes from string to integer" in state
                            and "(absent)" not in state)
                return {question.id: one_hot("intended" if intended else "unsure", list(question.criteria))}
            return super().evaluate(state, questions, reasons=reasons)

    intent = tmp_path / "intent.md"
    intent.write_text("The services use separate databases. On GET /items, $[*].code changes from string to integer.")
    spec = {"paths": {"/items": {"get": {}}}}
    responses = {"before": [{"code": "1", "name": "old"}], "after": [{"code": 2}]}

    def get(request):
        return httpx.Response(200, json=responses[request.url.host])

    cfg = pipeline.RunConfig("http://before", "http://after", intent=intent, answer_key=None)
    with httpx.Client(transport=httpx.MockTransport(get)) as client:
        run = pipeline.run(cfg, client, IntentEvaluator(AnswerKey()), specs=(spec, spec))
    assert [(f.path, f.label, f.status) for f in run.findings] == [
        ("$[*].code", "intended", "accepted"),
        ("$[*].name", "unsure", "unsure"),
    ]
