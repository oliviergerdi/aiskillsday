"""Deterministic noise removal, applied to both sides before diffing."""

from __future__ import annotations

import copy
import json
from typing import Any

from nparity import jsonpath
from nparity.config import NoiseRules
from nparity.models import HttpResult, Noise

MASK = "<masked>"


def _sort_key(key: str | None):
    def k(item: Any) -> Any:
        if key and isinstance(item, dict) and key in item:
            return (0, json.dumps(item[key], sort_keys=True, default=str))
        return (1, json.dumps(item, sort_keys=True, default=str))
    return k


def normalise(endpoint: str, old: HttpResult, new: HttpResult, rules: NoiseRules,
              renames: dict[str, str | None] | None = None) -> tuple[HttpResult, HttpResult, list[Noise]]:
    """`endpoint` is the old key. `renames` maps old top-level field -> new name, or None for a dropped field.

    Noise is recorded only when a rule actually changed something on either side.
    """
    ob, nb = copy.deepcopy(old.body), copy.deepcopy(new.body)
    noise: list[Noise] = []

    if isinstance(ob, dict):
        for old_name, new_name in (renames or {}).items():
            if old_name not in ob:
                continue
            value = ob.pop(old_name)
            if new_name is not None:
                ob[new_name] = value

    for rule in (r for r in rules.mask if r.endpoint == endpoint):
        for path in rule.paths:
            a, b = jsonpath.get(ob, path), jsonpath.get(nb, path)
            if a is jsonpath.MISSING and b is jsonpath.MISSING:
                continue
            if a != b:
                noise.append(Noise(endpoint=endpoint, path=path, rule="mask"))
            jsonpath.set_(ob, path, MASK)
            jsonpath.set_(nb, path, MASK)

    for rule in (r for r in rules.unordered if r.endpoint == endpoint):
        changed = False
        for body in (ob, nb):
            items = jsonpath.get(body, rule.path)
            if isinstance(items, list):
                ordered = sorted(items, key=_sort_key(rule.key))
                if ordered != items:
                    changed = True
                    jsonpath.set_(body, rule.path, ordered)
        if changed:
            noise.append(Noise(endpoint=endpoint, path=rule.path, rule=f"unordered by {rule.key or 'content'}"))

    return old.model_copy(update={"body": ob}), new.model_copy(update={"body": nb}), noise
