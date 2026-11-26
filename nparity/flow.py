"""Suggest operation flows from specs. No operation in a suggested flow is replayed."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import unquote

from nparity.config import Thresholds
from nparity.evaluator.base import Backend, Choice, TooManyOptions, tally
from nparity.models import FlowCitation, FlowMap, FlowMapping, FlowStep, Telemetry
from nparity.openapi import METHODS, resolve

ROLES = {
    "direct": "Direct replacement for the entire old operation",
    "auth": "Obtain credentials needed by another step",
    "configure": "Select or set up the configuration used by the flow",
    "start": "Start the workflow or create the resource",
    "await": "Wait for completion by webhook, callback or polling",
    "read": "Read information or results",
    "page": "Read results that use pagination",
    "none": "Unrelated: a caller does not need this operation to reproduce the before outcome",
}
GENERIC = {
    "id", "status", "type", "data", "name", "result", "api", "get", "post", "list", "create",
    "read", "service", "internal", "return", "response", "operation", "request",
}
PAGE_FIELDS = {"cursor", "page", "pagenumber", "pagesize", "limit", "offset", "pagetoken", "nextcursor"}
PATH_PARAMETER = re.compile(r"\{[^}]*\}")


def _identifiers(names: set[str]) -> set[str]:
    """Only ids and tokens hand work from one call to the next. A body that repeats a response is not a dependency."""
    return {name for name in names if name.endswith("id") or name in {"accesstoken", "token"}}


def _method(key: str) -> str | None:
    head = key.split(" ", 1)[0].lower()
    return head if head in METHODS else None


def _normal(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _words(value: str) -> set[str]:
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    return {word.removesuffix("s") if len(word) > 3 else word
            for word in re.findall(r"[a-z][a-z0-9]+", value.lower()) if word not in GENERIC} - GENERIC


def _schemas(document: dict) -> list[dict]:
    return ([document["schema"]] if "schema" in document else []) + [
        media.get("schema", {}) for media in document.get("content", {}).values()
    ]


def _fields(schema: dict, *, required: bool = False) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    properties = schema.get("properties", {})
    names = set(schema.get("required", ())) if required else set(properties)
    children = [properties[name] for name in names if name in properties]
    for part in ("allOf", "anyOf", "oneOf"):
        children.extend(schema.get(part, ()))
    if "items" in schema:
        children.append(schema["items"])
    return {_normal(name) for name in names}.union(*(_fields(child, required=required) for child in children))


def _pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


@dataclass
class Operation:
    key: str
    reference: str
    path: str
    operation_id: str
    tags: set[str]
    words: set[str]
    fields: set[str]
    requires: set[str]
    provides: set[str]
    source: FlowCitation
    sources: dict[str, str]
    links: set[str]
    dependencies: set[str] = field(default_factory=set)
    asynchronous: bool = False
    paged: bool = False

    def prompt(self) -> dict:
        description = self.sources.get(f"{self.reference}/description", "")
        return {"operation": self.key, "operation_id": self.operation_id, "tags": sorted(self.tags),
                "source_excerpt": self.source.quote, "description": description[:800], "required_inputs": sorted(self.requires),
                "outputs": sorted(self.provides), "dependencies": sorted(self.dependencies),
                "callback_or_webhook": self.asynchronous, "pagination_parameters": self.paged}


def _operation(spec: dict, item: dict, raw: dict, key: str, path: str, reference: str,
               *, owner: str | None = None, asynchronous: bool = False) -> Operation:
    op = resolve({k: v for k, v in raw.items() if k != "callbacks"}, spec)
    parameters = {(p["in"], p["name"]): p for p in
                  [*resolve(item.get("parameters", []), spec), *op.get("parameters", [])]}
    body = op.get("requestBody", {}) or next((p for p in parameters.values() if p["in"] == "body"), {})
    inputs = {_normal(name) for location, name in parameters if location != "body"}
    requires = {_normal(name) for (location, name), p in parameters.items()
                if location == "path" or (location != "body" and p.get("required"))}
    body_fields: set[str] = set()
    schemes = spec.get("components", {}).get("securitySchemes", {}) or spec.get("securityDefinitions", {})
    security = op.get("security", spec.get("security", []))
    if security and all(any(schemes.get(name, {}).get("type") == "oauth2"
                            or schemes.get(name, {}).get("scheme", "").lower() == "bearer"
                            for name in option) for option in security):
        requires.add("accesstoken")
    for schema in _schemas(body):
        body_fields |= _fields(schema)
        if body.get("required", True):
            requires |= _fields(schema, required=True)
    inputs |= body_fields

    # Event recipients can use the fields delivered in the callback or webhook payload.
    provides = body_fields.copy() if asynchronous else set()
    if owner:
        requires.clear()
    links: set[str] = set()
    sources = {}
    for field_name in ("summary", "description", "operationId"):
        value = op.get(field_name)
        if isinstance(value, str) and value.strip():
            sources[f"{reference}/{field_name}"] = value
    for status, response in op.get("responses", {}).items():
        if not str(status).startswith("2"):
            continue
        for schema in _schemas(response):
            provides |= _fields(schema)
        for link in response.get("links", {}).values():
            if target := link.get("operationId") or link.get("operationRef"):
                links.add(unquote(target))
        if description := response.get("description"):
            sources[f"{reference}/responses/{status}/description"] = description
    sources[reference] = path
    source_ref, source_text = next(iter(sources.items()))
    quote = source_text.strip().splitlines()[0][:300]
    tags = set(op.get("tags", ()))
    operation_id = op.get("operationId", "")
    words = _words(PATH_PARAMETER.sub("", path)) | _words(operation_id) | _words(op.get("summary", ""))
    return Operation(
        key, reference, path, operation_id, tags, words, (inputs | provides) - GENERIC,
        requires - GENERIC, provides - GENERIC, FlowCitation(reference=source_ref, quote=quote), sources, links,
        dependencies={owner} if owner else set(), asynchronous=asynchronous,
        paged=bool(inputs & PAGE_FIELDS),
    )


def operations(spec: dict) -> list[Operation]:
    result = []
    for path, item in spec.get("paths", {}).items():
        if "$ref" in item:
            item = resolve(item, spec)
        for method in METHODS:
            if method not in item:
                continue
            op = item[method]
            key = f"{method.upper()} {path}"
            ref = f"#/paths/{_pointer(path)}/{method}"
            result.append(_operation(spec, item, op, key, path, ref))
            for name, callback in op.get("callbacks", {}).items():
                resolved = resolve(callback, spec)
                for expression, callback_item in resolved.items():
                    for verb in METHODS:
                        if verb in callback_item:
                            callback_key = f"callback {name} ({key})"
                            if len(resolved) > 1 or sum(v in callback_item for v in METHODS) > 1:
                                callback_key += f" {verb.upper()} {expression}"
                            callback_ref = f"{ref}/callbacks/{_pointer(name)}/{_pointer(expression)}/{verb}"
                            result.append(_operation(spec, callback_item, callback_item[verb], callback_key,
                                                     expression, callback_ref, owner=key, asynchronous=True))
    for name, item in spec.get("webhooks", {}).items():
        item = resolve(item, spec)
        for method in METHODS:
            if method in item:
                key = f"webhook {name}"
                if sum(verb in item for verb in METHODS) > 1:
                    key += f" ({method.upper()})"
                result.append(_operation(spec, item, item[method], key, name,
                                         f"#/webhooks/{_pointer(name)}/{method}", asynchronous=True))

    for op in result:
        for other in result:
            if op.key == other.key:
                continue
            linked = other.operation_id in op.links or other.reference in op.links
            shared_ids = _identifiers(op.provides & other.requires) if not (op.asynchronous and other.asynchronous) else set()
            if linked or shared_ids:
                other.dependencies.add(op.key)
    return sorted(result, key=lambda op: op.key)


def candidates(old: Operation, new: list[Operation]) -> list[Operation]:
    selected = set()
    old_path = PATH_PARAMETER.sub("{}", old.path)
    for op in new:
        shared_words = old.words & op.words
        if (old_path == PATH_PARAMETER.sub("{}", op.path) or (old.operation_id and old.operation_id == op.operation_id)
                or old.fields & op.fields or len(shared_words) >= 2 or (shared_words and old.tags & op.tags)):
            selected.add(op.key)
    remaining = {op.key: op for op in new}
    # Include prerequisites and downstream steps even when their names differ.
    pending = list(selected)
    while pending:
        key = pending.pop()
        for op in remaining.values():
            if op.key not in selected and (op.key in remaining[key].dependencies or key in op.dependencies):
                selected.add(op.key)
                pending.append(op.key)
    return sorted((remaining[key] for key in selected), key=lambda op: op.key)


def verify_source(citation: FlowCitation, op: Operation) -> FlowCitation | None:
    if citation.quote.strip() and citation.quote in op.sources.get(citation.reference, ""):
        return citation
    return None


def ordered_steps(steps: list[FlowStep], dependencies: dict[str, set[str]]) -> tuple[list[FlowStep], str | None]:
    pending = {step.new_op: step for step in steps}
    ordered = []
    while pending:
        ready = sorted(key for key in pending if not (dependencies[key] & pending.keys()))
        if not ready:
            ordered.extend(pending[key] for key in sorted(pending))
            return ordered, "The spec dependencies contain a cycle. Review the order of the remaining steps."
        # Recheck after every step so unrelated nodes do not postpone a newly available prerequisite.
        ordered.append(pending.pop(ready[0]))
    return ordered, None


def map_flows(old_spec: dict, new_spec: dict, ev: Backend, thresholds: Thresholds,
              tel: Telemetry, workers: int = 8) -> FlowMapping:
    old, new = operations(old_spec), operations(new_spec)
    pairs = [(op, candidate) for op in old for candidate in candidates(op, new)]
    if pairs and ev.max_options < len(ROLES):
        raise TooManyOptions(f"Flow mapping needs {len(ROLES)} choices per question.")
    minimum = thresholds.mapping.needs_review

    def classify(pair):
        old_op, new_op = pair
        q = Choice(id="flow:" + json.dumps([old_op.key, new_op.key]), criteria=ROLES,
                   instructions=f"What role does {new_op.key} serve for a caller replacing {old_op.key} "
                                f"({old_op.source.quote})? Choose direct only if this one operation alone does what the old "
                                f"operation did: the same resource and the same action. Creating, updating and deleting "
                                f"are different actions, so a sibling operation that does another action is not direct. "
                                f"Choose none if it is unrelated to this goal.")
        answer = ev.evaluate({"before": old_op.prompt(), "after": new_op.prompt()}, [q])[q.id]
        return answer

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        answers = list(pool.map(classify, pairs))
    tally(tel, answers)
    grouped: dict[str, list[FlowStep]] = {op.key: [] for op in old}
    none_count = 0
    for (old_op, new_op), answer in zip(pairs, answers):
        role = answer.value if answer.value in ROLES else "none"
        warning = answer.meta.get("error")
        unsure = (answer.censored or answer.off_list or bool(warning) or answer.value not in ROLES
                  or (minimum is not None and answer.p_winner < minimum))
        if role == "none" and not unsure:
            none_count += 1
            continue
        quote = answer.meta.get("quote", new_op.source.quote)
        citation = FlowCitation(reference=new_op.source.reference, quote=quote) if isinstance(quote, str) else None
        source = verify_source(citation, new_op) if citation else None
        if source is None:
            unsure = True
            warning = warning or "The source quote could not be verified."
        grouped[old_op.key].append(FlowStep(new_op=new_op.key, role=role, p=answer.p_winner,
                                            status="unsure" if unsure else "suggested", source=source, warning=warning))
    for old_key, steps in grouped.items():
        def same_method(step: FlowStep) -> bool:
            return _method(step.new_op) in (None, _method(old_key))

        directs = [step for step in steps if step.role == "direct" and step.status == "suggested"]
        best = max((step for step in directs if same_method(step)), key=lambda step: step.p, default=None)
        for i, step in enumerate(steps):
            if step not in directs:
                continue
            if not same_method(step):
                warning = "Direct replacement uses a different HTTP method. Review it."
            elif step is not best:
                warning = "Another operation is the more likely direct replacement. Review it."
            else:
                continue
            steps[i] = step.model_copy(update={"status": "unsure", "warning": warning})
    dependencies = {op.key: op.dependencies for op in new}
    result = FlowMapping(none_count=none_count)
    placed = set()
    for old_op, steps in grouped.items():
        ordered, warning = ordered_steps(steps, dependencies)
        if ordered:
            result.flows.append(FlowMap(old_op=old_op, steps=ordered, ordering_warning=warning))
        linked = {step.new_op for step in steps if step.status == "suggested"}
        if not linked:
            result.unmatched_old.append(old_op)
        placed |= linked
    result.unmatched_new = [op.key for op in new if op.key not in placed]
    return result
