"""Compare the declared API contract independently of live findings."""

from nparity.models import ContractChange, EndpointMap
from nparity.openapi import Endpoint

ANNOTATIONS = {"summary", "description", "title", "example", "examples", "externalDocs"}
SCHEMA_MAPS = {"properties", "patternProperties", "dependentSchemas", "$defs", "definitions"}
INLINE_SCHEMA_FIELDS = {
    "type", "format", "items", "default", "enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minLength", "maxLength", "pattern", "minItems", "maxItems", "uniqueItems", "multipleOf", "x-nullable",
}


def structure(value):
    if isinstance(value, list):
        return [structure(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in ANNOTATIONS:
            continue
        if key == "type" and item == "file":
            result.update(type="string", format="binary")
            continue
        if key == "x-nullable":
            key = "nullable"
        if key in SCHEMA_MAPS and isinstance(item, dict):
            result[key] = {name: structure(schema) for name, schema in item.items()}
        elif key in {"required", "enum"} and isinstance(item, list):
            result[key] = sorted(item, key=repr)
        else:
            result[key] = structure(item)
    return result


def _parameter(parameter: dict, location: str) -> dict:
    schema = parameter.get("schema", {key: value for key, value in parameter.items() if key in INLINE_SCHEMA_FIELDS})
    definition = {"schema": structure(schema), "required": location == "path" or bool(parameter.get("required"))}
    if isinstance(schema, dict) and schema.get("type") in ("array", "object"):
        collection_format = parameter.get("collectionFormat")
        default_style = "form" if location == "query" else "simple"
        if collection_format is not None or ("schema" not in parameter and location == "query"):
            style = {"ssv": "spaceDelimited", "pipes": "pipeDelimited", "tsv": "tabDelimited"}.get(
                collection_format, default_style,
            )
            explode = collection_format == "multi"
        else:
            style = parameter.get("style", default_style)
            explode = parameter.get("explode", style == "form")
        definition["serialization"] = {"style": style, "explode": explode}
    for name in ("allowEmptyValue", "allowReserved", "content", "deprecated"):
        if parameter.get(name):
            definition[name] = structure(parameter[name])
    return definition


def _request_body(endpoint: Endpoint) -> dict:
    body = endpoint.request_body
    if "schema" in body:
        content = {media: {"schema": body["schema"]} for media in endpoint.consumes or ["*/*"]}
        return {"required": bool(body.get("required")), "content": structure(content)}
    if body:
        return {"required": bool(body.get("required")), "content": structure(body.get("content", {}))}
    form = [p for p in endpoint.parameters if p["in"] == "formData"]
    if not form:
        return {}
    fields = {p["name"]: _parameter(p, "formData")["schema"] for p in form}
    required = sorted(p["name"] for p in form if p.get("required"))
    schema = {"type": "object", "properties": fields}
    if required:
        schema["required"] = required
    content = {media: {"schema": schema} for media in endpoint.consumes or ["application/x-www-form-urlencoded"]}
    return {"required": bool(required), "content": content}


def _response(response: dict, media_types: list[str]) -> dict:
    content = response.get("content", {})
    if "schema" in response:
        content = {media: {"schema": response["schema"]} for media in media_types or ["*/*"]}
    result = {}
    if content:
        result["content"] = structure(content)
    if headers := response.get("headers"):
        result["headers"] = {name.lower(): _parameter(header, "header") for name, header in headers.items()}
    if links := response.get("links"):
        result["links"] = structure(links)
    return result


def sections(endpoint: Endpoint) -> dict:
    return {
        "parameters": {
            f"{p['in']} {p['name']}": _parameter(p, p["in"])
            for p in endpoint.parameters if p["in"] not in ("body", "formData")
        },
        "request body": _request_body(endpoint),
        "responses": {str(status): _response(response, endpoint.produces) for status, response in endpoint.responses.items()},
    }


def compare(old: list[Endpoint], new: list[Endpoint], mappings: list[EndpointMap]) -> list[ContractChange]:
    after = {endpoint.key: endpoint for endpoint in new}
    exact = {ep.key for ep in old} & after.keys()
    remapped = {m.old: m.new for m in mappings if m.status == "accepted" and m.new not in exact}
    matched = set()
    changes = []
    for endpoint in old:
        target = endpoint.key if endpoint.key in exact else remapped.get(endpoint.key)
        replacement = after.get(target)
        if replacement is None or target in matched:
            changes.append(ContractChange(endpoint=endpoint.key, section="operation", before=sections(endpoint)))
            continue
        matched.add(target)
        if endpoint.key != replacement.key:
            changes.append(ContractChange(endpoint=endpoint.key, new_endpoint=replacement.key, section="operation",
                                          before=endpoint.key, after=replacement.key))
        after_sections = sections(replacement)
        for section, before in sections(endpoint).items():
            later = after_sections[section]
            if before != later:
                changes.append(ContractChange(endpoint=endpoint.key, new_endpoint=replacement.key, section=section,
                                              before=before, after=later))
    for endpoint in new:
        if endpoint.key not in matched:
            changes.append(ContractChange(endpoint=endpoint.key, new_endpoint=endpoint.key, section="operation",
                                          after=sections(endpoint)))
    return changes
