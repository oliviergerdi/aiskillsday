"""Resolve the sources entered in the local run form."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urljoin

import httpx
import yaml
from pydantic import BaseModel, Field

DOCUMENT_LIMIT = 10 * 1024 * 1024
CAPTURE_PATH = "/captured-response"
CAPTURE_SPEC = {"paths": {CAPTURE_PATH: {"get": {}}}}


class InputError(ValueError):
    pass


class SourceInput(BaseModel):
    kind: Literal["api", "spec", "manifest"]
    source: str = Field(min_length=1, max_length=4096, pattern=r"\S")
    base_url: str = Field(default="", max_length=4096)


@dataclass(frozen=True)
class Source:
    base_url: str
    spec: dict
    capture: tuple[int, object] | None = None
    label: str | None = None


def local_file(value: str, suffixes: set[str]) -> Path:
    path = Path(value).expanduser()
    if path.suffix.lower() not in suffixes or not path.is_file():
        raise InputError(f"Choose an existing local {'/'.join(sorted(suffixes))} file.")
    if path.stat().st_size > DOCUMENT_LIMIT:
        raise InputError("Local files must be 10 MiB or smaller.")
    return path


def http_url(value: str, *, base: bool = False) -> httpx.URL:
    try:
        parsed = httpx.URL(value)
    except (httpx.InvalidURL, ValueError):
        raise InputError("Enter a valid HTTP or HTTPS URL.") from None
    if (parsed.scheme not in {"http", "https"} or not parsed.host
            or parsed.userinfo or parsed.fragment or (base and parsed.query)):
        raise InputError("Enter an HTTP or HTTPS URL without credentials or a fragment. API base URLs cannot contain a query.")
    return parsed


def is_spec(data: object) -> bool:
    return isinstance(data, dict) and ("openapi" in data or "swagger" in data) and isinstance(data.get("paths"), dict)


def read_document(client: httpx.Client, source: str) -> tuple[object, str | None]:
    try:
        if source.lower().startswith(("https://", "http://")):
            with client.stream("GET", http_url(source)) as response:
                response.raise_for_status()
                content = bytearray()
                for chunk in response.iter_bytes():
                    content.extend(chunk)
                    if len(content) > DOCUMENT_LIMIT:
                        raise InputError("API documents must be 10 MiB or smaller.")
                return yaml.safe_load(bytes(content)), str(response.url)
        path = local_file(source, {".json", ".yaml", ".yml"})
        return yaml.safe_load(path.read_bytes()), None
    except (yaml.YAMLError, UnicodeError):
        raise InputError("The API document could not be parsed as JSON or YAML.") from None


def server_url(spec: dict, document_url: str | None) -> str:
    if spec.get("swagger") == "2.0" and spec.get("host"):
        origin_scheme = httpx.URL(document_url).scheme if document_url else "https"
        schemes = spec.get("schemes") or [origin_scheme]
        scheme = origin_scheme if origin_scheme in schemes else schemes[0]
        candidate = f"{scheme}://{spec['host']}{spec.get('basePath', '/')}"
    else:
        server = (spec.get("servers") or [{}])[0]
        candidate = server.get("url", spec.get("basePath", "/"))
        for name, variable in server.get("variables", {}).items():
            if "default" in variable:
                candidate = candidate.replace("{" + name + "}", str(variable["default"]))
    if document_url:
        candidate = urljoin(document_url, candidate)
    if not candidate.startswith(("http://", "https://")) or "{" in candidate:
        raise InputError("Enter an API base URL for this spec. Its server URL is relative or incomplete.")
    return str(http_url(candidate, base=True))


def from_manifest(value: str, override: str, side: str) -> Source:
    filename, _, pair_name = value.partition("#")
    manifest = local_file(filename, {".json"})
    try:
        data = json.loads(manifest.read_bytes())
        pairs = data["pairs"]
        if not isinstance(pairs, list) or not pairs:
            raise InputError("The manifest has no comparison pairs.")
        if not pair_name and len(pairs) != 1:
            raise InputError("Add #pair_name to choose a pair from this manifest.")
        pair = next((p for p in pairs if p["name"] == pair_name), None) if pair_name else pairs[0]
        if pair is None:
            raise InputError("The named pair was not found in the manifest.")
        entry = pair[side]
        url = http_url(entry["url"])
        capture_file = (manifest.parent / entry["file"]).resolve()
        if not capture_file.is_relative_to(manifest.parent.resolve()):
            raise InputError("Manifest files must be inside the manifest directory.")
        capture_file = local_file(str(capture_file), {".json"})
        data = json.loads(capture_file.read_bytes())
        if is_spec(data):
            base = str(http_url(override, base=True)) if override else server_url(data, str(url))
            return Source(base, data)
        status = entry["http_status"]
        if type(status) is not int or not 100 <= status <= 599:
            raise InputError("The manifest must specify a valid HTTP status for the saved response.")
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeError):
        raise InputError("Use a JSON manifest with named pairs, old/new entries, and referenced JSON files.") from None
    label = str(url.copy_with(query=None))
    return Source(f"http://{side}.capture.invalid", CAPTURE_SPEC, (status, data), label)


def resolve_source(client: httpx.Client, target: SourceInput, side: str) -> Source:
    source, override = target.source.strip(), target.base_url.strip()
    if target.kind == "manifest":
        return from_manifest(source, override, side)
    if target.kind == "api":
        base = str(http_url(source, base=True))
        for filename in ("openapi.json", "swagger.json"):
            try:
                data, _ = read_document(client, f"{base.rstrip('/')}/{filename}")
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code not in {404, 405}:
                    raise
                continue
            except InputError:
                continue
            if is_spec(data):
                return Source(base, data)
        raise InputError("No OpenAPI document found. Choose Swagger / OpenAPI and enter the spec location.")
    data, document_url = read_document(client, source)
    if not is_spec(data):
        raise InputError("The document must be a Swagger or OpenAPI spec with a paths section.")
    base = str(http_url(override, base=True)) if override else server_url(data, document_url)
    return Source(base, data)
