"""In-process audit jobs: one at a time, bounded queue, offline engines only, uploads deleted afterwards."""

from __future__ import annotations

import queue
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evalpilot.config import Settings

HOSTED_NOTE = ("hosted audit: offline engines only (code rules, secrets, bandit, config review, code graders); "
               "LLM judges are offline stubs and URL probing is disabled")
KEEP_UPLOAD_AUDITS = 20


class QueueFull(RuntimeError):
    pass


@dataclass
class Upload:
    workdir: Path
    traces: Path | None = None
    trace_version: str | None = None
    system_card: Path | None = None
    code_zip: Path | None = None


@dataclass
class Job:
    job_id: str
    status: str = "queued"
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished: str | None = None
    audit_id: str | None = None
    decision: str | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=lambda: [HOSTED_NOTE])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


Runner = Callable[[Upload], tuple[str, str]]


def offline_runner(settings: Settings, out_dir: Path) -> Runner:
    def run(upload: Upload) -> tuple[str, str]:
        from evalpilot.audit.intake import AuditInputs
        from evalpilot.audit.run import AuditOptions, run_audit

        inputs = AuditInputs(system_card=upload.system_card, traces=upload.traces, trace_version=upload.trace_version,
                             zip_path=upload.code_zip)
        options = AuditOptions(provider="offline", out_dir=out_dir, ai_review=False)
        result = run_audit(settings, inputs, options)
        _prune(out_dir)
        return result.audit_id, result.verdict.decision

    return run


def _prune(out_dir: Path) -> None:
    audits = sorted((p for p in out_dir.glob("audit-*") if p.is_dir()), key=lambda p: p.name)
    for old in audits[:-KEEP_UPLOAD_AUDITS]:
        shutil.rmtree(old, ignore_errors=True)


class JobQueue:
    def __init__(self, runner: Runner, *, max_queued: int, max_kept: int, inline: bool = False) -> None:
        self.runner = runner
        self.max_kept = max_kept
        self.inline = inline
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[tuple[Job, Upload]] = queue.Queue(maxsize=max_queued)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def submit(self, upload: Upload) -> Job:
        job = Job(job_id=uuid.uuid4().hex[:16])
        with self._lock:
            self.jobs[job.job_id] = job
            for old in list(self.jobs)[: max(0, len(self.jobs) - self.max_kept)]:
                del self.jobs[old]
        if self.inline:
            self._execute(job, upload)
            return job
        try:
            self._queue.put_nowait((job, upload))
        except queue.Full:
            with self._lock:
                self.jobs.pop(job.job_id, None)
            shutil.rmtree(upload.workdir, ignore_errors=True)
            raise QueueFull("audit queue is full; try again in a minute") from None
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self.jobs.get(job_id)

    def _ensure_worker(self) -> None:
        with self._lock:
            if self._worker is None or not self._worker.is_alive():
                self._worker = threading.Thread(target=self._loop, name="evalpilot-audit-jobs", daemon=True)
                self._worker.start()

    def _loop(self) -> None:
        while True:
            job, upload = self._queue.get()
            try:
                self._execute(job, upload)
            finally:
                self._queue.task_done()

    def _execute(self, job: Job, upload: Upload) -> None:
        job.status = "running"
        try:
            job.audit_id, job.decision = self.runner(upload)
            job.status = "done"
        except Exception as exc:  # the worker must survive bad uploads
            from evalpilot.audit.intake import IntakeError
            from evalpilot.models import ValidationError

            if isinstance(exc, (IntakeError, ValidationError, ValueError)):
                job.error = str(exc).replace(str(upload.workdir), "<upload>")
            else:
                job.error = "audit failed (internal error)"
            job.status = "failed"
        finally:
            job.finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
            shutil.rmtree(upload.workdir, ignore_errors=True)
