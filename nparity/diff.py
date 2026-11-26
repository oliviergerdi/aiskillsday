"""Value diff per JSON path. Deterministic: numbers, rounding, counts and pagination are caught here."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nparity.jsonpath import child
from nparity.models import FindingKind, HttpResult


@dataclass
class Diff:
    path: str
    kind: FindingKind
    old: Any
    new: Any


def json_class(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _walk(a: Any, b: Any, path: str, out: list[Diff]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(Diff(child(path, k), "missing_in_new", a[k], None))
            else:
                _walk(a[k], b[k], child(path, k), out)
        for k in b:
            if k not in a:
                out.append(Diff(child(path, k), "added_in_new", None, b[k]))
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(Diff(path, "list_length_changed", len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, child(path, i), out)
        return
    if json_class(a) != json_class(b):
        out.append(Diff(path, "type_changed", a, b))
    elif a != b:
        out.append(Diff(path, "changed", a, b))


def diff(old: HttpResult, new: HttpResult) -> list[Diff]:
    if old.error or new.error:
        return []
    out: list[Diff] = []
    if old.status != new.status:
        out.append(Diff("status", "status_changed", old.status, new.status))
    _walk(old.body, new.body, "$", out)
    return out
