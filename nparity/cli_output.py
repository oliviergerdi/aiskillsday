"""Machine-readable CLI results, failures, and exit statuses."""

from __future__ import annotations

import json
import sys
from enum import StrEnum

import httpx
import typer
import yaml
from pydantic import ValidationError
from typer._click.exceptions import UsageError
from typer.core import TyperGroup

from nparity.models import Finding, Run
from nparity.review import finding_key

EXIT_GATE = 5


class FindingFilter(StrEnum):
    REGRESSION = "regression"
    UNSURE = "unsure"
    INTENDED = "intended"
    ERROR = "error"


class Gate(StrEnum):
    REGRESSION = "regression"
    UNSURE = "unsure"
    ERROR = "error"


FINDING_STATES = {"regression": "shown", "unsure": "unsure", "intended": "accepted", "error": "error"}


def emit_json(payload, *, stderr: bool = False) -> None:
    typer.echo(json.dumps(payload, ensure_ascii=False, allow_nan=False), err=stderr)


def error_record(exc: Exception) -> tuple[int, dict]:
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in {408, 429} or status >= 500:
            return 3, {"code": "upstream_unavailable", "message": f"Upstream returned HTTP {status}.", "retryable": True}
        return 4, {"code": "upstream_rejected", "message": f"Upstream returned HTTP {status}.", "retryable": False}
    if isinstance(exc, httpx.TransportError):
        return 3, {"code": "transport_error", "message": "Could not complete an upstream request.", "retryable": True}
    if isinstance(exc, FileNotFoundError):
        return 2, {"code": "not_found", "message": str(exc), "retryable": False}
    if isinstance(exc, ValidationError):
        issue = exc.errors(include_input=False, include_context=False)[0]
        field = ".".join(map(str, issue["loc"]))
        return 2, {"code": "invalid_input", "message": f"{field}: {issue['msg']}", "retryable": False}
    if isinstance(exc, (httpx.InvalidURL, yaml.YAMLError)):
        message = "Invalid URL." if isinstance(exc, httpx.InvalidURL) else "Could not read a YAML input."
        return 2, {"code": "invalid_input", "message": message, "retryable": False}
    if isinstance(exc, (UsageError, ValueError)):
        message = exc.format_message() if isinstance(exc, UsageError) else str(exc)
        return 2, {"code": "invalid_input", "message": message, "retryable": False}
    if isinstance(exc, typer.Abort):
        return 130, {"code": "interrupted", "message": "The command was interrupted.", "retryable": False}
    return 4, {"code": "run_failed", "message": "The command could not complete.", "retryable": False}


def _requests_json(args) -> bool:
    options = {}
    for index, argument in enumerate(args):
        if argument == "--":
            break
        key, equals, value = argument.partition("=")
        if key in {"--format", "--progress"}:
            options[key] = value if equals else (args[index + 1] if index + 1 < len(args) else "")
    return options.get("--format") == "json" or options.get("--progress") == "jsonl"


class AgentGroup(TyperGroup):
    """Keep JSON-mode diagnostics parseable, including errors during argument parsing."""

    def main(self, args=None, *, standalone_mode=True, **kwargs):
        if not _requests_json(sys.argv[1:] if args is None else args):
            return super().main(args, standalone_mode=standalone_mode, **kwargs)
        try:
            code = super().main(args, standalone_mode=False, **kwargs)
        except Exception as exc:
            code, error = error_record(exc)
            emit_json({"error": error}, stderr=True)
        if standalone_mode:
            raise SystemExit(code or 0)
        return code


def gate_failures(run: Run, rules: list[Gate]) -> list[str]:
    statuses = {finding.status for finding in run.findings}
    if run.errors:
        statuses.add("error")
    return sorted({rule.value for rule in rules if FINDING_STATES[rule.value] in statuses})


def gate_error(run_id: str, failures: list[str]) -> dict:
    return {"code": "gate_failed", "message": "Run completed with " + ", ".join(failures) + ".",
            "retryable": False, "run_id": run_id, "conditions": failures}


def compact_run(run: Run, filters: list[FindingFilter] | None = None, endpoint: str | None = None,
                limit: int = 50, offset: int = 0) -> dict:
    statuses = {FINDING_STATES[value.value] for value in filters or []}
    selected = [f for f in run.findings + run.errors
                if (not statuses or f.status in statuses) and (endpoint is None or f.endpoint == endpoint)]
    counts = {
        "regressions": sum(f.status == "shown" for f in run.findings),
        "unsure": sum(f.status == "unsure" for f in run.findings),
        "intended": sum(f.status == "accepted" for f in run.findings),
        "errors": len(run.errors),
        "noise": len(run.noise),
        "declared_differences": len(run.contract),
    }
    return {
        "id": run.id, "started_at": run.started_at.isoformat(), "backend": run.config.get("backend"),
        "counts": counts, "telemetry": json.loads(run.telemetry.model_dump_json()),
        "coverage": {
            "endpoints": len(run.coverage),
            "contract_compared": sum(row.contract_compared for row in run.coverage),
            "behaviour_compared": sum(row.compared > 0 for row in run.coverage),
        },
        "warning": run.basic_checks_summary(),
        "findings": [_finding_summary(f) for f in selected[offset:offset + limit]],
        "page": {"total": len(selected), "limit": limit, "offset": offset,
                 "next_offset": offset + limit if offset + limit < len(selected) else None},
    }


def _finding_summary(finding: Finding) -> dict:
    return {"id": finding.id, "key": finding_key(finding), "endpoint": finding.endpoint,
            "new_endpoint": finding.new_endpoint, "path": finding.path, "kind": finding.kind, "status": finding.status}
