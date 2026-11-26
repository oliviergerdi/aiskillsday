"""Generate endpoint-specific seeds and record where each value came from."""

from __future__ import annotations

import math
from typing import Any

import httpx

from nparity.config import OperationSeeds, Seeds, SeedSource, SeedValue
from nparity.map import stems
from nparity.models import Request
from nparity.openapi import Endpoint
from nparity.replay import fill

VALUE_LIMIT = 5
PATH_SOURCES = {"manual", "example", "default", "discovered", "sample"}
SOURCE_RANK = {"manual": 0, "example": 1, "default": 1, "enum": 2, "bounds": 2,
               "discovered": 3, "sample": 4, "guessed": 5}


def tagged(values: list[Any], source: SeedSource) -> list[SeedValue]:
    unique = []
    for value in values:
        if value is not None and value not in unique:
            unique.append(value)
        if len(unique) == VALUE_LIMIT:
            break
    return [SeedValue(value=value, source=source) for value in unique]


def explicit_values(schema: dict) -> list[SeedValue]:
    examples = schema.get("examples") or []
    if isinstance(examples, dict):
        examples = [entry["value"] for entry in examples.values() if isinstance(entry, dict) and "value" in entry]
    elif not isinstance(examples, list):
        examples = []
    candidates = ([schema["example"]] if "example" in schema else []) + examples
    return tagged(candidates, "example") or tagged([schema.get("default")], "default")


def schema_values(schema: dict, *, path: bool = False) -> list[SeedValue]:
    if not isinstance(schema, dict):
        return []
    explicit = explicit_values(schema)
    if explicit:
        return explicit
    for branch in schema.get("oneOf") or schema.get("anyOf") or []:
        if values := schema_values(branch, path=path):
            return values
    if path:
        return []
    if values := tagged(schema.get("enum", []), "enum"):
        return values
    kind = schema.get("type")
    if isinstance(kind, list):
        kind = next((name for name in kind if name != "null"), None)
    if kind in ("integer", "number"):
        lower, upper = schema.get("minimum"), schema.get("maximum")
        for name, lower_bound in (("exclusiveMinimum", True), ("exclusiveMaximum", False)):
            bound = schema.get(name)
            inclusive = lower if lower_bound else upper
            if bound is True and inclusive is not None:
                bound = inclusive
            if type(bound) in (int, float):
                direction = math.inf if lower_bound else -math.inf
                value = (math.floor(bound) + 1 if lower_bound else math.ceil(bound) - 1) if kind == "integer" else math.nextafter(bound, direction)
                if lower_bound:
                    lower = max(lower, value) if lower is not None else value
                else:
                    upper = min(upper, value) if upper is not None else value
        if kind == "integer":
            lower = math.ceil(lower) if lower is not None else None
            upper = math.floor(upper) if upper is not None else None
        if lower is not None and upper is not None and lower > upper:
            return []
        if values := tagged([lower, upper], "bounds"):
            return values
    if kind == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        required = required if isinstance(required, list) else []
        values = {name: schema_values(properties.get(name, {})) for name in required}
        if all(values.values()):
            return tagged([{name: choices[0].value for name, choices in values.items()}], "guessed")
        return []
    if kind == "array" and isinstance(schema.get("items"), dict):
        if candidates := schema_values(schema["items"]):
            return tagged([[candidates[0].value] * max(1, min(VALUE_LIMIT, schema.get("minItems", 0)))], "guessed")
    guesses = {"integer": 1, "number": 1.0, "string": "test", "boolean": True}
    return tagged([guesses.get(kind)], "guessed")


def body_values(body: dict) -> list[SeedValue]:
    for content in body.get("content", {}).values():
        if values := explicit_values(content) or schema_values(content.get("schema", {})):
            return values
    return explicit_values(body) or schema_values(body.get("schema", {}))


def from_spec(endpoints: list[Endpoint]) -> dict[str, OperationSeeds]:
    result = {}
    for endpoint in endpoints:
        params = {}
        for param in endpoint.parameters:
            if param["in"] not in ("path", "query"):
                continue
            values = explicit_values(param) or schema_values(param.get("schema", param), path=param["in"] == "path")
            if values:
                params[param["name"]] = values
        bodies = body_values(endpoint.request_body)
        if params or bodies:
            result[endpoint.key] = OperationSeeds(params=params, bodies=bodies)
    return result


def fill_gaps(seeds: Seeds, generated: dict[str, OperationSeeds]) -> Seeds:
    result = seeds.model_copy(deep=True)
    for endpoint, suggested in generated.items():
        existing = result.operations.setdefault(endpoint, OperationSeeds())
        for name, values in suggested.params.items():
            previous = existing.params.get(name, [])
            if name not in existing.params or (previous and SOURCE_RANK[values[0].source] < SOURCE_RANK[previous[0].source]):
                existing.params[name] = values
        if suggested.bodies and (not existing.bodies
                                 or SOURCE_RANK[suggested.bodies[0].source] < SOURCE_RANK[existing.bodies[0].source]):
            existing.bodies = suggested.bodies
    return result


def records(body: Any) -> list[dict]:
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    if isinstance(body, dict):
        return [body] + [item for value in body.values() if isinstance(value, list) for item in records(value)]
    return []


def identifier_names(parameter: str) -> set[str]:
    name = parameter.lower().replace("_", "").replace("-", "")
    return {name, "id"} if name.endswith("id") else {name}


def harvest(endpoints: list[Endpoint], responses: list[tuple[str, Any]], seeds: Seeds, source: SeedSource) -> None:
    available = [(stems(path), records(body)) for path, body in responses]
    lower_priority = {"guessed"} if source == "sample" else {"sample", "guessed"}
    for endpoint in endpoints:
        if endpoint.method != "GET" or not endpoint.params:
            continue
        operation = seeds.operations.get(endpoint.key, OperationSeeds())
        resource = stems(endpoint.path)
        for name in endpoint.params:
            existing = operation.params.get(name, [])
            if name in seeds.params or (existing and existing[0].source not in lower_priority):
                continue
            matching = identifier_names(name)
            values = [
                value for response_resource, rows in available if response_resource & resource
                for row in rows for key, value in row.items()
                if key.lower().replace("_", "").replace("-", "") in matching and type(value) in (str, int, float)
            ]
            if values := tagged(values, source):
                operation.params[name] = values
                seeds.operations[endpoint.key] = operation


def discover(endpoints: list[Endpoint], requests: list[Request], client: httpx.Client, base: str, seeds: Seeds) -> None:
    """Fill missing seeds from explicitly allowlisted GET requests."""
    responses = []
    for request in requests:
        if request.method != "GET" or request.body is not None:
            continue
        path, params = fill(request)
        try:
            response = client.get(base.rstrip("/") + path, params=params, follow_redirects=False)
            response.raise_for_status()
            responses.append((request.path, response.json()))
        except (httpx.HTTPError, ValueError):
            continue
    harvest(endpoints, responses, seeds, "discovered")
