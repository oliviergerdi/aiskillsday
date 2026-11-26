"""Compare the declared API contract independently of live findings."""

from nparity.models import ContractChange, EndpointMap
from nparity.openapi import Endpoint

ANNOTATIONS = {"summary", "description", "title", "example", "examples", "externalDocs"}
SCHEMA_MAPS = {"properties", "patternProperties", "dependentSchemas", "$defs", "definitions"}


def structure(value):
    if isinstance(value, list):
        return [structure(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, item in value.items():
        if key in ANNOTATIONS:
            continue
        if key in SCHEMA_MAPS and isinstance(item, dict):
            result[key] = {name: structure(schema) for name, schema in item.items()}
        elif key in {"required", "enum"} and isinstance(item, list):
            result[key] = sorted(item, key=repr)
        else:
            result[key] = structure(item)
    return result


def sections(endpoint: Endpoint) -> dict:
    return {
        "parameters": {
            f"{p['in']} {p['name']}": structure(p)
            for p in endpoint.parameters if p["in"] != "body"
        },
        "request body": structure(endpoint.request_body),
        "responses": {str(status): structure(response) for status, response in endpoint.responses.items()},
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
