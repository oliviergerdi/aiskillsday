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


def value_at(obj: Any, path: str) -> Any:
    """Like get(), but also walks list indexes: $.items[0].id. Returns MISSING when absent."""
    if path in ("$", ""):
        return obj
    cur = obj
    for name, idx, kname, kval in _TOKEN.findall(path.removeprefix("$")):
        if kname:
            if not isinstance(cur, list):
                return MISSING
            cur = next((i for i in cur if isinstance(i, dict) and str(i.get(kname)) == kval), MISSING)
            if cur is MISSING:
                return MISSING
        elif idx:
            i = int(idx)
            if not isinstance(cur, list) or i >= len(cur):
                return MISSING
            cur = cur[i]
        else:
            if not isinstance(cur, dict) or name not in cur:
                return MISSING
            cur = cur[name]
    return cur
