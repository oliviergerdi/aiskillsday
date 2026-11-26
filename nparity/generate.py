"""OpenAPI endpoints x seed values -> requests (a few samples per endpoint)."""

from __future__ import annotations

from itertools import islice, product

from nparity.config import OperationSeeds, Seeds, SeedValue
from nparity.models import Request
from nparity.openapi import Endpoint
from nparity.seed_generation import PATH_SOURCES


def generate(eps: list[Endpoint], seeds: Seeds, cap: int = 5) -> list[Request]:
    """Cross seeded values per endpoint, at most `cap` requests each.

    Skipped: endpoints with a required param that has no seed, and body endpoints with no seeded body.
    Optional query params without seeds are simply left out.
    """
    out: list[Request] = []
    allowed = allowed_methods(seeds)
    for ep in eps:
        if ep.method not in allowed:
            continue
        operation = seeds.operations.get(ep.key, OperationSeeds())
        pools = {}
        for name in ep.params:
            if name in seeds.params:
                values = [SeedValue(value=value, source="manual") for value in seeds.params[name]]
            else:
                values = operation.params.get(name, [])
            if name in ep.path_params:
                values = [value for value in values if value.source in PATH_SOURCES]
            if values:
                pools[name] = values
        if not ep.required <= pools.keys():
            continue
        bodies = [None]
        if ep.has_body:
            bodies = (
                [SeedValue(value=value, source="manual") for value in seeds.bodies[ep.key]]
                if ep.key in seeds.bodies else operation.bodies
            )
            if not bodies:
                continue
        combos = product(bodies, *pools.values())
        for body, *values in islice(combos, cap):
            params = {name: seed.value for name, seed in zip(pools, values)}
            sources = {name: seed.source for name, seed in zip(pools, values)}
            if body is not None:
                sources["$body"] = body.source
            out.append(Request(method=ep.method, path=ep.path, params=params,
                               body=body.value if body is not None else None, seed_sources=sources))
    return out


def allowed_methods(seeds: Seeds) -> set[str]:
    return {method.upper() for method in seeds.methods} if seeds.methods is not None else {"GET"}
