"""Deterministic noise removal, applied to both sides before diffing.

Order: accepted renames, explicit `mask` rules, then one parallel walk over both bodies that
- replaces per-call values (datetimes, dates, UUIDs, epoch timestamps) with their *format* (PRD 0002),
  so a value that differs per call compares equal while a change of format still shows up, and
- records order-only differences in keyed lists as noise (the diff matches those lists by key).
"""

from __future__ import annotations

import copy
import re
from typing import Any

from nparity import jsonpath
from nparity.config import NoiseRules
from nparity.lists import by_key, key_segment, stable_key
from nparity.models import HttpResult, Noise

MASK = "<masked>"

DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ](\d{2}:\d{2})(:\d{2}(\.(\d+))?)?(Z|[+-]\d{2}:?\d{2})?$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-([0-9a-fA-F])[0-9a-fA-F]{3}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
EPOCH_FIELD = re.compile(r"(At|_at|Date|_date)$|^(timestamp|created|updated)$")


def format_token(value: Any, field: str | None, rules: NoiseRules) -> tuple[str, str] | None:
    """(token, rule kind) for a per-call value, keeping its format; None when it isn't one."""
    if isinstance(value, str):
        m = DATETIME.match(value)
        if m and rules.default_on("datetime"):
            frac = m.group(4)
            precision = "min" if not m.group(2) else ("s" if not frac else ("ms" if len(frac) <= 3 else "us"))
            tz = m.group(5) or "naive"
            if tz not in ("Z", "naive") and ":" not in tz:
                tz = tz[:3] + ":" + tz[3:]
            return f"<datetime tz={tz} precision={precision}>", "datetime"
        if DATE.match(value) and rules.default_on("date"):
            return "<date>", "date"
        m = UUID.match(value)
        if m and rules.default_on("uuid"):
            return f"<uuid v{m.group(1)}>", "uuid"
    if (isinstance(value, int) and not isinstance(value, bool) and field and EPOCH_FIELD.search(field)
            and 10**9 <= value < 10**13 and rules.default_on("epoch")):
        return ("<epoch s>" if value < 10**11 else "<epoch ms>"), "epoch"
    return None


class _Walk:
    def __init__(self, endpoint: str, rules: NoiseRules):
        self.endpoint = endpoint
        self.rules = rules
        self.keys = rules.list_keys(endpoint)
        self.noise: dict[tuple[str, str], Noise] = {}

    def note(self, path: str, rule: str) -> None:
        g = jsonpath.generic(path)
        self.noise.setdefault((g, rule), Noise(endpoint=self.endpoint, path=g, rule=rule))

    def pair(self, a: Any, b: Any, path: str, field: str | None, parent: Any, slot: Any) -> None:
        """Walk aligned values. `parent[slot]` is where (a, b) live, so tokens can replace them in place."""
        if isinstance(a, dict) and isinstance(b, dict):
            for k in a.keys() & b.keys():
                self.pair(a[k], b[k], jsonpath.child(path, k), k, (a, b), k)
            return
        if isinstance(a, list) and isinstance(b, list):
            k = stable_key(a, b, self.keys.get(jsonpath.generic(path)))
            if k:
                ma, mb = by_key(a, k), by_key(b, k)
                if list(ma) != list(mb) and set(ma) == set(mb):
                    self.note(path, f"order (matched by {k})")
                for key in ma.keys() & mb.keys():
                    self.pair(ma[key], mb[key], path + key_segment(k, key), None, None, None)
                return
            for i, (x, y) in enumerate(zip(a, b)):
                self.pair(x, y, jsonpath.child(path, i), field, (a, b), i)
            return
        if a == b or parent is None:
            return
        ta, tb = format_token(a, field, self.rules), format_token(b, field, self.rules)
        pa, pb = parent
        if ta and tb and ta[0] == tb[0]:
            pa[slot] = pb[slot] = ta[0]
            self.note(path, f"{ta[1]} (format kept)")
        elif ta and tb and type(a) is not type(b):
            return          # e.g. ISO string -> epoch int: keep raw values so the diff reports type_changed
        else:
            if ta:
                pa[slot] = ta[0]
            if tb:
                pb[slot] = tb[0]


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

    walk = _Walk(endpoint, rules)
    box = [ob, nb]
    walk.pair(ob, nb, "$", None, None, None)
    noise.extend(walk.noise.values())
    return old.model_copy(update={"body": box[0]}), new.model_copy(update={"body": box[1]}), noise
