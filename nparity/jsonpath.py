"""Tiny dotted-path helpers: "$", "$.a.b", "$.items[0].id". Enough for the prototype, not JSONPath."""

from __future__ import annotations

import re
from typing import Any

_MISSING = object()


def parts(path: str) -> list[str]:
    if path in ("$", ""):
        return []
    return path.removeprefix("$.").split(".")


def get(obj: Any, path: str) -> Any:
    """Value at path, or MISSING."""
    cur = obj
    for p in parts(path):
        if not isinstance(cur, dict) or p not in cur:
            return _MISSING
        cur = cur[p]
    return cur


def set_(obj: Any, path: str, value: Any) -> bool:
    ps = parts(path)
    cur = obj
    for p in ps[:-1]:
        if not isinstance(cur, dict) or p not in cur:
            return False
        cur = cur[p]
    if not ps or not isinstance(cur, dict) or ps[-1] not in cur:
        return False
    cur[ps[-1]] = value
    return True


def child(path: str, key: str | int) -> str:
    return f"{path}[{key}]" if isinstance(key, int) else f"{path}.{key}"


def generic(path: str) -> str:
    """$.items[3].id and $.items[id=10].id -> $.items[*].id, for grouping types across samples."""
    return re.sub(r"\[[^\]]*\]", "[*]", path)


MISSING = _MISSING


_TOKEN = re.compile(r"([^.\[\]]+)|\[(\d+)\]|\[([^=\]]+)=([^\]]*)\]")


def locate(obj: Any, path: str) -> tuple[Any, list[str | int]] | None:
    """Return the value and its concrete keys and indexes, or None if absent."""
    cur = obj
    positions: list[str | int] = []
    for name, idx, kname, kval in _TOKEN.findall(path.removeprefix("$")):
        if name:
            if not isinstance(cur, dict) or name not in cur:
                return None
            key = name
        elif isinstance(cur, list):
            key = int(idx) if idx else next(
                (i for i, item in enumerate(cur) if isinstance(item, dict) and str(item.get(kname)) == kval),
                len(cur),
            )
            if key >= len(cur):
                return None
        else:
            return None
        positions.append(key)
        cur = cur[key]
    return cur, positions


def value_at(obj: Any, path: str) -> Any:
    """Like get(), with support for list indexes and keys. Returns MISSING when absent."""
    result = locate(obj, path)
    return result[0] if result is not None else MISSING
