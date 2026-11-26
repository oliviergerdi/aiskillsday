"""Run comparisons in the background and retain their recent console output."""

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock, Thread
from typing import Literal
from uuid import uuid4

import httpx
import yaml
from pydantic import ValidationError

from app.web.configs import DEFAULT_DIR as CONFIGS_DIR, RunInput, config_path, save_config
from app.web.run_sources import InputError, local_file, resolve_source
from nparity import pipeline, store
from nparity.config import Seeds, load_seeds
from nparity.evaluator.fake import FakeBackend
from nparity.models import AnswerKey
from nparity.retry import RetryPolicy
from nparity.review import latest_baseline, scope_of
from nparity.tls import tls_verify

LOG = logging.getLogger(__name__)
HISTORY_LIMIT = 32


@dataclass
class Job:
    state: str = "running"
    lines: list[str] = field(default_factory=lambda: ["Starting comparison"])
    report_url: str | None = None
    field: str | None = None
    error_message: str | None = None


class RunJobs:
    def __init__(self) -> None:
        self.jobs: dict[str, Job] = {}
        self.lock = Lock()

    def start(self, inputs: RunInput, directory: Path, configs: Path = CONFIGS_DIR) -> str | None:
        with self.lock:
            if any(job.state == "running" for job in self.jobs.values()):
                return None
            if len(self.jobs) == HISTORY_LIMIT:
                del self.jobs[next(iter(self.jobs))]
            job_id = uuid4().hex
            job = self.jobs[job_id] = Job()
            Thread(target=self.run, args=(job_id, job, inputs, directory, configs), daemon=True).start()
            return job_id

    def status(self, job_id: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(job_id)
            if job is not None:
                error = {"field": job.field, "message": job.error_message} if job.field else None
                return {"state": job.state, "lines": list(job.lines), "report_url": job.report_url, "error": error}
        return None

    def run(self, job_id: str, job: Job, inputs: RunInput, directory: Path, configs: Path = CONFIGS_DIR) -> None:
        def progress(message: str) -> None:
            with self.lock:
                job.lines.append(message)

        try:
            report_id = compare(job_id, inputs, directory, progress, configs)
        except InputError as exc:
            message = str(exc)
            if exc.field:
                with self.lock:
                    job.field, job.error_message, job.state = exc.field, message, "failed"
                return
        except httpx.HTTPStatusError as exc:
            message = f"The API document returned HTTP {exc.response.status_code}. Check the source URL."
        except httpx.RequestError:
            message = "Could not reach the API document. Check the URL, network, and TLS settings."
        except (OSError, ValidationError, yaml.YAMLError):
            message = "Could not read the input files or save the report. Check file formats and permissions."
        except Exception:
            LOG.exception("Comparison %s failed", job_id)
            message = "Comparison failed during the last stage shown. See the server log for details."
        else:
            with self.lock:
                job.lines.append("Report saved")
                job.report_url = f"/runs/{report_id}"
                job.state = "complete"
            return
        with self.lock:
            job.lines.append(f"Error: {message}")
            job.state = "failed"


def compare(job_id: str, inputs: RunInput, directory: Path, progress: Callable[[str], None],
            configs: Path = CONFIGS_DIR) -> str:
    if inputs.backend == "flash" and not os.environ.get("FIREWORKS_API_KEY"):
        raise InputError("Set FIREWORKS_API_KEY in the server environment to use Flash.", "backend")
    defaults = pipeline.RunConfig("", "")
    try:
        seeds_path = local_file(inputs.seeds, {".yaml", ".yml"}) if inputs.seeds else defaults.seeds
    except InputError as exc:
        raise InputError(str(exc), "seeds") from exc
    if inputs.intent_text.strip():
        intent_dir = directory / f"{inputs.name}-{job_id[:12]}"
        intent_dir.mkdir(parents=True, exist_ok=True)
        intent_path = intent_dir / "intent.md"
        intent_path.write_text(inputs.intent_text, encoding="utf-8")
    else:
        try:
            intent_path = local_file(inputs.intent, {".md", ".txt"}) if inputs.intent else None
        except InputError as exc:
            raise InputError(str(exc), "intent") from exc
    seeds = load_seeds(seeds_path)
    if not inputs.seeds:
        seeds.methods = ["GET"]
    ev = FakeBackend(AnswerKey()) if inputs.backend == "fake" and not inputs.score else None

    with httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True) as client:
        progress("Loading before source")
        before = resolve_source(client, inputs.before, "old")
        progress("Loading after source")
        after = resolve_source(client, inputs.after, "new")
        config = pipeline.RunConfig(
            before.base_url, after.base_url, intent=intent_path, seeds=seeds_path,
            answer_key=defaults.answer_key if inputs.score else None,
            backend=inputs.backend, name=f"{inputs.name}-{job_id[:12]}",
        )
        options = {"specs": (before.spec, after.spec), "request_seeds": seeds, "progress": progress}
        if before.capture is None and after.capture is None:
            run = pipeline.run(config, client, ev, **options)
        elif before.capture is not None and after.capture is not None:
            captures = {"old.capture.invalid": before.capture, "new.capture.invalid": after.capture}

            def serve_capture(request: httpx.Request) -> httpx.Response:
                status, body = captures[request.url.host]
                return httpx.Response(status, json=body)

            config.retry = RetryPolicy(statuses=frozenset())
            options["request_seeds"] = Seeds()
            with httpx.Client(transport=httpx.MockTransport(serve_capture)) as offline:
                run = pipeline.run(config, offline, ev, **options)
            run.config.update(old=before.label, new=after.label)
        else:
            raise InputError("Choose saved responses for both sides to compare captures. Specs from a manifest can be combined with live API sources.")

    if inputs.save_config:
        save_config(inputs, configs)
        progress(f"Saved configuration {inputs.name}")
    if config_path(inputs.name, configs).is_file():
        run.config["config"] = inputs.name
    run.config["baseline"] = resolve_baseline(inputs.baseline, run, directory)
    if run.config["baseline"]:
        progress(f"Baseline: {run.config['baseline']}")
    if intent_path:
        run.config["intent_source"] = "form" if inputs.intent_text.strip() else "file"
    progress(f"Saving report with {len(run.findings)} findings and {len(run.errors)} errors")
    store.save(run, directory)
    return run.id


def resolve_baseline(choice: str, run, directory: Path) -> str | None:
    """'auto' = newest earlier run in the same scope; '' = none; otherwise an existing run id."""
    if not choice:
        return None
    if choice == "auto":
        b = latest_baseline(scope_of(run), store.list_runs(directory), before=run.started_at, exclude=run.id)
        return b.id if b else None
    try:
        return store.load(choice, directory).id
    except (FileNotFoundError, ValueError):
        return None
