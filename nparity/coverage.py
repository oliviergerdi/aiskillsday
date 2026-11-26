"""Record which endpoint requests supplied usable behaviour evidence."""

from collections import defaultdict

from nparity.models import EndpointCoverage, Sample
from nparity.openapi import Endpoint
from nparity.replay import path_params
from nparity.seed_generation import identifier_names, records

DATA_DIFFERS = "data differs, comparison not valid"


def _identity_matches(request, result) -> bool:
    for parameter in path_params(request.path):
        keys = identifier_names(parameter)
        values = {
            str(value) for record in records(result.body) for key, value in record.items()
            if key.lower().replace("_", "").replace("-", "") in keys
        }
        if values and str(request.params[parameter]) not in values:
            return False
    return True


def sample_issue(sample: Sample) -> str | None:
    if sample.new_request is None:
        return "no matching operation"
    old, new = sample.old, sample.new
    if old.error or new.error or old.status is None or new.status is None:
        return "request failed"
    if old.status >= 400 and old.status == new.status:
        return "both errors"
    identifiers = [name for name in path_params(sample.old_request.path) if "id" in identifier_names(name)]
    if identifiers and ((old.status in {404, 410} and 200 <= new.status < 300)
                        or (new.status in {404, 410} and 200 <= old.status < 300)):
        return DATA_DIFFERS
    if "discovered" in sample.old_request.seed_sources.values():
        if not (200 <= old.status < 300 and 200 <= new.status < 300
                and _identity_matches(sample.old_request, old) and _identity_matches(sample.new_request, new)):
            return DATA_DIFFERS
    return None


def report(old: list[Endpoint], new: list[Endpoint], samples: list[Sample], allowed: set[str],
           *, contract_available: bool, matched: set[str], contract_only: bool = False) -> list[EndpointCoverage]:
    per_endpoint = defaultdict(list)
    for sample in samples:
        per_endpoint[sample.old_request.endpoint].append(sample)
    old_keys = {ep.key for ep in old}
    rows = []
    for endpoint in old:
        pairs = per_endpoint[endpoint.key]
        issues = [sample_issue(sample) for sample in pairs]
        reasons = sorted({reason for reason in issues if reason is not None})
        if not pairs and contract_only:
            reasons = ["contract only"]
        elif not pairs and endpoint.method in allowed:
            reasons = ["not seeded"]
        elif not pairs:
            description = "mutating method" if endpoint.method in {"POST", "PUT", "PATCH", "DELETE"} else "method"
            reasons = [f"{description} not enabled"]
        sources = {source for sample in pairs for source in sample.old_request.seed_sources.values()}
        rows.append(EndpointCoverage(
            endpoint=endpoint.key, seed_sources=sorted(sources), contract_compared=contract_available,
            attempted=sum(sample.new_request is not None for sample in pairs),
            compared=issues.count(None),
            reason=", ".join(reasons) or None,
        ))
    if contract_available:
        rows.extend(EndpointCoverage(endpoint=ep.key, contract_compared=True, reason="no before sample")
                    for ep in new if ep.key not in old_keys | matched)
    return rows
