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


def observed_type(value: Any) -> str:
    return "integer" if type(value) is int else json_class(value)


def _shape(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple((name, _shape(item)) for name, item in sorted(value.items()))
    if isinstance(value, list):
        return frozenset(_shape(item) for item in value)
    return observed_type(value)


def _dynamic_map(schema: dict) -> bool:
    return not schema.get("properties") and (
        schema.get("additionalProperties") is True or isinstance(schema.get("additionalProperties"), dict)
    )


def _observed_types(values: list) -> set[str]:
    return {observed_type(value) for value in values}


def _walk_independent(before: list, after: list, path: str, out: list[Diff], schemas: tuple[dict, dict]) -> None:
    if not before or not after:
        return
    old_schema, new_schema = schemas
    old_types, new_types = _observed_types(before), _observed_types(after)
    if old_types != new_types:
        out.append(Diff(path, "type_changed", sorted(old_types), sorted(new_types)))
        return
    objects = [[value for value in values if isinstance(value, dict)] for values in (before, after)]
    if objects[0] and objects[1]:
        if _dynamic_map(old_schema) and _dynamic_map(new_schema):
            left, right = [[value for obj in side for value in obj.values()] for side in objects]
            a, b = old_schema["additionalProperties"], new_schema["additionalProperties"]
            _walk_independent(left, right, path, out, (a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}))
        else:
            names = set().union(*(value.keys() for side in objects for value in side))
            old_properties, new_properties = old_schema.get("properties", {}), new_schema.get("properties", {})
            for name in sorted(names):
                old_vals, new_vals = [[obj[name] for obj in side if name in obj] for side in objects]
                item_path = child(path, name)
                old_required = name in old_schema.get("required", [])
                new_required = name in new_schema.get("required", [])
                missing_required = new_required and len(new_vals) < len(objects[1]) and len(old_vals) == len(objects[0])
                missing_field = not new_vals and (new_required or name not in new_properties)
                if old_vals and (missing_required or missing_field):
                    out.append(Diff(item_path, "missing_in_new", old_vals[0], None))
                elif new_vals and not old_vals and (old_required or name not in old_properties):
                    out.append(Diff(item_path, "added_in_new", None, new_vals[0]))
                a = old_properties.get(name, {})
                b = new_properties.get(name, {})
                _walk_independent(old_vals, new_vals, item_path, out, (a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}))
    if "array" in old_types:
        left, right = [[item for array in values if isinstance(array, list) for item in array] for values in (before, after)]
        a, b = old_schema.get("items"), new_schema.get("items")
        _walk_independent(left, right, path + "[*]", out, (a if isinstance(a, dict) else {}, b if isinstance(b, dict) else {}))


def _walk(a: Any, b: Any, path: str, out: list[Diff], keys: dict[str, Any], shape_only: bool) -> None:
    if isinstance(a, dict) and isinstance(b, dict):
        for k in a:
            if k not in b:
                out.append(Diff(child(path, k), "missing_in_new", a[k], None))
            else:
                _walk(a[k], b[k], child(path, k), out, keys, shape_only)
        for k in b:
            if k not in a:
                out.append(Diff(child(path, k), "added_in_new", None, b[k]))
        return
    if isinstance(a, list) and isinstance(b, list):
        if shape_only:
            if a and b and _shape(a) != _shape(b):
                out.append(Diff(path, "type_changed", a, b))
            return
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
                    _walk(ma[x], mb[x], path + key_segment(k, x), out, keys, shape_only)
            return
        if len(a) != len(b):
            out.append(Diff(path, "list_length_changed", len(a), len(b)))
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, child(path, i), out, keys, shape_only)
        return
    if (shape_only and _shape(a) != _shape(b)) or json_class(a) != json_class(b):
        out.append(Diff(path, "type_changed", a, b))
    elif not shape_only and a != b:
        out.append(Diff(path, "changed", a, b))


def diff(old: HttpResult, new: HttpResult, list_keys: dict[str, Any] | None = None, *,
         shape_only: bool = False, independent_schemas: tuple[dict, dict] | None = None) -> list[Diff]:
    if old.error or new.error:
        return []
    out: list[Diff] = []
    if old.status != new.status:
        out.append(Diff("status", "status_changed", old.status, new.status))
    if independent_schemas is not None:
        _walk_independent([old.body], [new.body], "$", out, independent_schemas)
    else:
        _walk(old.body, new.body, "$", out, list_keys or {}, shape_only)
    return out
