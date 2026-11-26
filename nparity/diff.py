"""Value diff per JSON path. Deterministic: numbers, rounding, counts and pagination are caught here.

Lists of keyed objects (PRD 0002) are matched by key: paths like $.items[id=10].name, and items present on
only one side become one `items_removed` / `items_added` diff at the list path, carrying the keys.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nparity.jsonpath import child, generic
from nparity.lists import by_key, key_segment, stable_key
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


def _walk(a: Any, b: Any, path: str, out: list[Diff], keys: dict[str, Any]) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(Diff(child(path, k), "missing_in_new", a[k], None))
            else:
                _walk(a[k], b[k], child(path, k), out, keys)
        for k in b:
            if k not in a:
                out.append(Diff(child(path, k), "added_in_new", None, b[k]))
        return
    if isinstance(a, list) and isinstance(b, list):
        k = stable_key(a, b, keys.get(generic(path)))
        if k:
            ma, mb = by_key(a, k), by_key(b, k)
            removed = [x for x in ma if x not in mb]
            added = [x for x in mb if x not in ma]
            if removed:
                out.append(Diff(path, "items_removed", removed, None))
            if added:
                out.append(Diff(path, "items_added", None, added))
            for x in ma:
                if x in mb:
                    _walk(ma[x], mb[x], path + key_segment(k, x), out, keys)
            return
        if len(a) != len(b):
            out.append(Diff(path, "list_length_changed", len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, child(path, i), out, keys)
        return
    if json_class(a) != json_class(b):
        out.append(Diff(path, "type_changed", a, b))
    elif a != b:
        out.append(Diff(path, "changed", a, b))


def diff(old: HttpResult, new: HttpResult, list_keys: dict[str, Any] | None = None) -> list[Diff]:
    if old.error or new.error:
        return []
    out: list[Diff] = []
    if old.status != new.status:
        out.append(Diff("status", "status_changed", old.status, new.status))
    _walk(old.body, new.body, "$", out, list_keys or {})
    return out
