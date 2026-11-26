"""OpenAPI endpoints x seed values -> requests (a few samples per endpoint)."""

from __future__ import annotations

from itertools import islice, product

from nparity.config import Seeds
from nparity.models import Request
from nparity.openapi import Endpoint


def generate(eps: list[Endpoint], seeds: Seeds, cap: int = 5) -> list[Request]:
    """Cross seeded values per endpoint, at most `cap` requests each.

    Skipped: endpoints with a required param that has no seed, and body endpoints with no seeded body.
    Optional query params without seeds are simply left out.
    """
    out: list[Request] = []
    allowed = {m.upper() for m in seeds.methods} if seeds.methods else None
    for ep in eps:
        if allowed is not None and ep.method not in allowed:
            continue
        names = [n for n in ep.params if n in seeds.params]
        if any(n not in seeds.params for n in ep.required):
            continue
        bodies: list[object] = [None]
        if ep.has_body:
            bodies = seeds.bodies.get(ep.key, [])
            if not bodies:
                continue
        combos = product(bodies, *(seeds.params[n] for n in names))
        for body, *values in islice(combos, cap):
            out.append(Request(method=ep.method, path=ep.path, params=dict(zip(names, values)), body=body))
    return out
