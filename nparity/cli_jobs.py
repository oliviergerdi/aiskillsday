"""Durable progress for CLI runs, including detached processes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import uuid4

import httpx
from pydantic import TypeAdapter

from nparity import headers, pipeline, store
from nparity.cli_output import EXIT_GATE, Gate, error_record, gate_error, gate_failures
from nparity.models import Run
from nparity.tls import tls_verify

TERMINAL = {"complete", "failed"}
INTERRUPTED = {"code": "interrupted", "message": "The run was interrupted.", "retryable": False}


def validate_id(value: str) -> str:
    if not value or value in {".", ".."} or any(char in value for char in "/\\\0"):
        raise ValueError("Use an identifier without path separators.")
    return value


class Job:
    def __init__(self, directory: Path, run_id: str, data: dict | None = None):
        self.path = directory / ".jobs" / f"{validate_id(run_id)}.json"
        self.data = data if data is not None else {
            "run_id": run_id, "state": "queued", "exit_code": None, "events": [],
        }

    def record(self, event: str, message: str, **updates) -> dict:
        events = self.data["events"]
        entry = {"seq": len(events) + 1, "run_id": self.data["run_id"], "event": event,
                 "message": message, "timestamp": datetime.now(UTC).isoformat()}
        if stage := pipeline.stage_for(message):
            entry["stage"] = stage
        events.append(entry)
        self.data.update(updates)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent, delete=False) as pending:
            temporary = Path(pending.name)
            try:
                json.dump(self.data, pending, ensure_ascii=False, allow_nan=False)
                pending.close()
                temporary.replace(self.path)
            finally:
                temporary.unlink(missing_ok=True)
        return entry

    def complete(self, path: Path, failures: list[str]) -> dict:
        error = gate_error(self.data["run_id"], failures) if failures else None
        return self.record("complete", "Report saved.", state="complete", saved_to=str(path),
                           exit_code=EXIT_GATE if failures else 0, error=error)

    def fail(self, code: int, error: dict) -> dict:
        return self.record("failed", error["message"], state="failed", exit_code=code, error=error)


def start(directory: Path, name: str) -> Job:
    date = datetime.now().astimezone().strftime("%Y-%m-%dT%H%M%S")
    job = Job(directory, f"{date}-{validate_id(name)}-{uuid4().hex[:12]}")
    job.record("queued", "Run accepted.")
    return job


def read(directory: Path, run_id: str, *, after: int = 0, wait: float = 0) -> dict:
    job = Job(directory, run_id)
    deadline = time.monotonic() + wait
    while True:
        data = json.loads(job.path.read_text(encoding="utf-8"))
        if data["state"] == "running" and data.get("pid") is not None:
            try:
                os.kill(data["pid"], 0)
            except ProcessLookupError:
                data = json.loads(job.path.read_text(encoding="utf-8"))
                if data["state"] == "running":
                    job.data = data
                    job.fail(4, {"code": "worker_terminated", "message": "The run process exited before saving a report.",
                                 "retryable": False})
            except PermissionError:
                pass
        data["events"] = [event for event in data["events"] if event["seq"] > after]
        remaining = deadline - time.monotonic()
        if data["events"] or data["state"] in TERMINAL or remaining <= 0:
            return data
        time.sleep(min(0.2, remaining))


def api_client() -> httpx.Client:
    return httpx.Client(timeout=30, verify=tls_verify(), follow_redirects=True,
                        headers={"User-Agent": headers.API_USER_AGENT})


def execute(cfg: pipeline.RunConfig, directory: Path, client: httpx.Client, progress) -> tuple[Run, Path]:
    run = pipeline.run(cfg, client, progress=progress)
    progress("Saving report")
    return run, store.save(run, directory)


def detach(cfg: pipeline.RunConfig, directory: Path, gates: list[Gate]) -> None:
    payload = json.loads(TypeAdapter(pipeline.RunConfig).dump_json(cfg))
    command = [sys.executable, "-m", "nparity.cli_jobs", str(directory), cfg.run_id]
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    with process.stdin:
        process.stdin.write(json.dumps({"config": payload, "gates": gates}).encode("utf-8"))


def _worker(directory: Path, run_id: str) -> None:
    job = Job(directory, run_id, read(directory, run_id))
    job.record("started", "Run started.", state="running", pid=os.getpid())

    def interrupt(*_):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    try:
        payload = json.load(sys.stdin)
        cfg = TypeAdapter(pipeline.RunConfig).validate_python(payload["config"])
        gates = [Gate(value) for value in payload["gates"]]
        with api_client() as client:
            run, path = execute(cfg, directory, client, lambda message: job.record("progress", message))
        job.complete(path, gate_failures(run, gates))
    except KeyboardInterrupt:
        job.fail(130, INTERRUPTED)
    except Exception as exc:
        code, error = error_record(exc)
        job.fail(code, error)


if __name__ == "__main__":
    _worker(Path(sys.argv[1]), sys.argv[2])
