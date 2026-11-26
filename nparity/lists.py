"""Stable keys for lists of objects (PRD 0002): match list items by key, not by position."""

from __future__ import annotations

from typing import Any

KEYS = ("id", "uuid", "key", "code")
NO_KEY = object()   # override meaning "compare by position"


def _qualifies(items: list[Any], k: str) -> bool:
    if not all(isinstance(i, dict) and k in i and isinstance(i[k], (str, int)) and not isinstance(i[k], bool)
               for i in items):
        return False
    values = [i[k] for i in items]
    return len(values) == len(set(values))


def stable_key(a: Any, b: Any, override: Any = None) -> str | None:
    """The field that identifies items in both lists, or None for positional compare.

    Every item on both sides must be an object with that field (str or int), unique per side.
    `override` is a key name from config, NO_KEY to force positional, or None to detect.
    """
    if not (isinstance(a, list) and isinstance(b, list)) or not (a or b) or override is NO_KEY:
        return None
    for k in ([override] if override else KEYS):
        if _qualifies(a, k) and _qualifies(b, k):
            return k
    return None


def by_key(items: list[dict], k: str) -> dict[Any, dict]:
    return {i[k]: i for i in items}


def key_segment(k: str, value: Any) -> str:
    return f"[{k}={value}]"


def membership(a: Any, b: Any, override: Any = None) -> tuple[str, list, list] | None:
    """(key, keys only in a, keys only in b) for two keyed lists, else None. For display text."""
    k = stable_key(a, b, override)
    if not k:
        return None
    ma, mb = by_key(a, k), by_key(b, k)
    return k, [x for x in ma if x not in mb], [x for x in mb if x not in ma]


def keys_text(k: str, keys: list, cap: int = 10) -> str:
    shown = ", ".join(f"{k}={x}" for x in keys[:cap])
    return shown + (f" and {len(keys) - cap} more" if len(keys) > cap else "")
