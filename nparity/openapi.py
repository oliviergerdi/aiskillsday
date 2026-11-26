"""Read an OpenAPI spec into a flat list of endpoints with resolved schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

METHODS = ("get", "post", "put", "patch", "delete")


@dataclass
class Endpoint:
    method: str
    path: str
    path_params: list[str] = field(default_factory=list)
    query_params: list[str] = field(default_factory=list)
    required: set[str] = field(default_factory=set)
    response_schema: dict[str, Any] | None = None
    has_body: bool = False

    @property
    def key(self) -> str:
        return f"{self.method} {self.path}"

    @property
    def params(self) -> list[str]:
        return self.path_params + self.query_params


def load_spec(client: httpx.Client, base_url: str, spec: str | None = None) -> dict[str, Any]:
    """Spec from `spec` (URL or local JSON/YAML file), else <base_url>/openapi.json."""
    import json
    from pathlib import Path

    import yaml

    if spec and not spec.startswith(("http://", "https://")):
        text = Path(spec).read_text(encoding="utf-8")
        return json.loads(text) if spec.endswith(".json") else yaml.safe_load(text)
    resp = client.get(spec or f"{base_url.rstrip('/')}/openapi.json")
    resp.raise_for_status()
    try:
        return resp.json()
    except ValueError:
        return yaml.safe_load(resp.text)


def resolve(node: Any, spec: dict[str, Any], _seen: frozenset[str] = frozenset()) -> Any:
    """Inline every local $ref. Cycles are left as {"$ref": ...}."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/"):
            if ref in _seen:
                return node
            target: Any = spec
            for part in ref[2:].split("/"):
                target = target[part]
            return resolve(target, spec, _seen | {ref})
        return {k: resolve(v, spec, _seen) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve(v, spec, _seen) for v in node]
    return node


def _response_schema(op: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any] | None:
    for status, resp in sorted(op.get("responses", {}).items()):
        if not str(status).startswith("2"):
            continue
        resp = resolve(resp, spec)
        content = resp.get("content", {})
        media = content.get("application/json") or next(
            (v for k, v in content.items() if "json" in k), {})
        schema = media.get("schema") or resp.get("schema")       # OpenAPI 3, else Swagger 2.0
        if schema:
            return resolve(schema, spec)
    return None


def endpoints(spec: dict[str, Any]) -> list[Endpoint]:
    out: list[Endpoint] = []
    for path, item in spec.get("paths", {}).items():
        for method in METHODS:
            op = item.get(method)
            if op is None:
                continue
            ep = Endpoint(method=method.upper(), path=path)
            for p in op.get("parameters", []) + item.get("parameters", []):
                p = resolve(p, spec)
                if p["in"] == "path":
                    ep.path_params.append(p["name"])
                elif p["in"] == "query":
                    ep.query_params.append(p["name"])
                if p.get("required") or p["in"] == "path":
                    ep.required.add(p["name"])
            ep.has_body = "requestBody" in op or any(
                resolve(p, spec).get("in") == "body" for p in op.get("parameters", []))
            ep.response_schema = _response_schema(op, spec)
            out.append(ep)
    return sorted(out, key=lambda e: (e.path, e.method))
