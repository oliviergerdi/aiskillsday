"""Type checks: observed (JSON values across samples) and declared (OpenAPI schemas of mapped fields)."""

from __future__ import annotations

from typing import Any

from nparity.diff import Diff
from nparity.jsonpath import child, generic
from nparity.map import props, type_name
from nparity.models import FieldMap, Sample


def value_type(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, float):
        frac = repr(v).split(".")[1] if "." in repr(v) else ""
        return f"decimal({len(frac.rstrip('0')) or 0})"
    if isinstance(v, str):
        return "string"
    if isinstance(v, list):
        return "array"
    return "object"


def _leaves(v: Any, path: str, out: dict[str, set[str]]) -> None:
    out.setdefault(generic(path), set()).add(value_type(v))
    if isinstance(v, dict):
        for k, x in v.items():
            _leaves(x, child(path, k), out)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _leaves(x, child(path, i), out)


def observed_types(samples: list[Sample]) -> dict[str, tuple[set[str], set[str]]]:
    """generic path -> (types seen in old, types seen in new). A path absent on one side has an empty set."""
    old: dict[str, set[str]] = {}
    new: dict[str, set[str]] = {}
    for s in samples:
        if not (s.old.error or s.new.error):
            _leaves(s.old.body, "$", old)
            _leaves(s.new.body, "$", new)
    return {p: (old.get(p, set()), new.get(p, set())) for p in sorted(set(old) | set(new))}


def describe_schema(schema: dict[str, Any], required: bool) -> str:
    parts = [type_name(schema)]
    if schema.get("format"):
        parts[0] += f" ({schema['format']})"
    if schema.get("enum"):
        parts.append("enum " + "|".join(map(str, schema["enum"])))
    parts.append("required" if required else "optional")
    return ", ".join(parts)


def declared_diffs(old_schema: dict[str, Any] | None, new_schema: dict[str, Any] | None,
                   fmap: list[FieldMap]) -> list[Diff]:
    """Compare mapped top-level fields' declared types. Paths use the old field name."""
    op, np_ = props(old_schema), props(new_schema)
    oreq = set((old_schema or {}).get("required", []))
    nreq = set((new_schema or {}).get("required", []))
    out: list[Diff] = []
    for f in fmap:
        if f.new is None or f.old not in op or f.new not in np_ or f.status == "unmapped":
            continue
        a = describe_schema(op[f.old], f.old in oreq)
        b = describe_schema(np_[f.new], f.new in nreq)
        if a != b:
            out.append(Diff(f"$.{f.old}", "declared_type_changed", a, b))
    return out
