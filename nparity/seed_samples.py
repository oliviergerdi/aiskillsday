"""Extract candidate seeds from saved requests and responses without executing them."""

import json
import re
import shlex
from pathlib import Path
from urllib.parse import unquote, urlsplit

import httpx

from nparity.config import OperationSeeds, Seeds, load_yaml
from nparity.openapi import Endpoint
from nparity.replay import fill, path_params
from nparity.request_samples import load_request_pairs
from nparity.seed_generation import harvest, tagged


def _option(tokens, *names):
    return next((value for flag, value in zip(tokens, tokens[1:]) if flag in names), None)


def _json_body(value):
    try:
        return json.loads(value) if value else None
    except (TypeError, ValueError):
        return None


def _curl_requests(path):
    for line in path.read_text(encoding="utf-8").replace("\\\n", " ").splitlines():
        tokens = shlex.split(line, comments=True)
        if not tokens or tokens[0] != "curl":
            continue
        url = _option(tokens, "--url") or next((token for token in tokens[1:] if token.startswith(("http://", "https://"))), "")
        data = _option(tokens, "-d", "--data", "--data-raw", "--data-binary", "--json")
        method = _option(tokens, "-X", "--request") or ("POST" if data else "GET")
        if url:
            yield method, url, {}, _json_body(data)


def _postman_requests(items):
    for item in items:
        yield from _postman_requests(item.get("item", []))
        request = item.get("request")
        if isinstance(request, str):
            yield "GET", request, {}, None
        elif isinstance(request, dict):
            location = request.get("url", "")
            if isinstance(location, dict):
                if not location.get("raw"):
                    values = {p["key"]: p["value"] for p in location.get("query", []) if not p.get("disabled")
                              and "key" in p and "value" in p}
                    yield request.get("method", "GET"), "/" + "/".join(location.get("path", [])), values, _json_body(request.get("body", {}).get("raw"))
                    continue
                location = location["raw"]
            yield request.get("method", "GET"), location, {}, _json_body(request.get("body", {}).get("raw"))


def _match_route(method, url, endpoints, base):
    path = urlsplit(re.sub(r"^\{\{[^{}]+\}\}", "", url)).path
    prefix = urlsplit(base).path.rstrip("/")
    if prefix and path.startswith(prefix + "/"):
        path = path[len(prefix):]
    routes = [endpoint for endpoint in endpoints if endpoint.method == method.upper()]
    for start in [0, *(index for index, char in enumerate(path) if char == "/" and index != 0)]:
        suffix = path[start:]
        for endpoint in routes:
            if endpoint.path == suffix:
                return endpoint, {}
        matches = []
        for endpoint in routes:
            segments = re.split(r"({[^{}]+})", endpoint.path)
            pattern = "".join("([^/]+)" if part.startswith("{") else re.escape(part) for part in segments)
            if matched := re.fullmatch(pattern, suffix):
                matches.append((endpoint, dict(zip(path_params(endpoint.path), map(unquote, matched.groups())))))
        if len(matches) == 1:
            return matches[0]
        if matches:
            break
    return None


def _coerce(param, value):
    kind = param.get("schema", param).get("type")
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "boolean":
            return {"true": True, "false": False}[str(value).lower()]
    except (ValueError, TypeError, KeyError):
        return None
    return value


def apply(path: Path, endpoints: list[Endpoint], seeds: Seeds, base: str = "") -> None:
    responses = []
    if path.suffix.lower() in {".curl", ".txt", ".sh"}:
        requests = list(_curl_requests(path))
    else:
        data = load_yaml(path)
        if isinstance(data, dict) and "item" in data:
            requests = list(_postman_requests(data["item"]))
        elif isinstance(data, dict) and "pairs" in data:
            requests = []
            for pair in data["pairs"]:
                entry = pair["old"]
                capture = (path.parent / entry["file"]).resolve()
                if capture.is_relative_to(path.parent.resolve()) and 200 <= entry.get("http_status", 200) < 300:
                    requests.append(("GET", entry["url"], {}, None))
                    responses.append((urlsplit(entry["url"]).path, json.loads(capture.read_bytes())))
        else:
            requests = []
            for pair in load_request_pairs(path):
                route, params = fill(pair.old)
                requests.append((pair.old.method, route, params, pair.old.body))
    for method, url, params, body in requests:
        if not (result := _match_route(method, url, endpoints, base)):
            continue
        endpoint, route_params = result
        params = {**dict(httpx.QueryParams(urlsplit(url).query)), **params, **route_params}
        operation = seeds.operations.setdefault(endpoint.key, OperationSeeds())
        for param in endpoint.parameters:
            name = param["name"]
            if name not in params or name in seeds.params or param["in"] not in {"path", "query"}:
                continue
            existing = operation.params.get(name, [])
            if existing and existing[0].source not in {"sample", "guessed"}:
                continue
            value = _coerce(param, params[name])
            if values := tagged([*(seed.value for seed in existing if seed.source == "sample"), value], "sample"):
                operation.params[name] = values
        if body is not None and endpoint.key not in seeds.bodies:
            if not operation.bodies or operation.bodies[0].source in {"sample", "guessed"}:
                operation.bodies = tagged([*(seed.value for seed in operation.bodies if seed.source == "sample"), body], "sample")
    harvest(endpoints, responses, seeds, "sample")
