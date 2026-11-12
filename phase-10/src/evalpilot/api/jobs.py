"""In-process audit jobs: one at a time, bounded queue, uploads deleted afterwards.

Phase 10 public `jobs` mode: URL + GitHub repo allowed; OpenAI when `OPENAI_API_KEY` is set, otherwise offline
judges with live HTTP probes. Admin (`serve --admin`, owner's machine): the owner's provider, labels, playground
and re-runs, all under the normal budget guard.
"""

from __future__ import annotations

import json
import queue
import shutil
import threading
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evalpilot.audit.models import ENGINES
from evalpilot.config import Settings

HOSTED_NOTE = ("hosted audit: offline engines only (code rules, secrets, bandit, config review, code graders); "
               "LLM judges are offline stubs and URL probing is disabled")
HOSTED_JOBS_NOTE = ("public hosted audit: URL and GitHub repo allowed; judges are offline until OPENAI_API_KEY is set "
                    "on Render; private/loopback targets are blocked when hosted")
PUBLIC_NOTE = ("public hosted audit: paid calls use the Render key under budget_usd; private/loopback targets are "
               "blocked; the spend ledger resets if the service restarts")
ADMIN_NOTE = "admin audit on the owner's machine: paid calls go through the budget guard and the spend ledger"
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
    # Public jobs (Phase 10) and admin: live URL / GitHub repo.
    target_url: str | None = None
    adapter: Path | None = None
    authorized: bool = False
    repo: str | None = None
    path: Path | None = None
    engines: list[str] | None = None
    ai_review: bool = False
    keep_workdir: bool = False
    on_progress: Callable[[str, str], None] | None = None


@dataclass
class Job:
    job_id: str
    name: str = ""
    status: str = "queued"
    created: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    finished: str | None = None
    audit_id: str | None = None
    decision: str | None = None
    error: str | None = None
    progress: dict[str, str] = field(default_factory=lambda: {e: "queued" for e in ENGINES})
    notes: list[str] = field(default_factory=lambda: [HOSTED_NOTE])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        progress = data.get("progress") if isinstance(data.get("progress"), dict) else {}
        notes = data.get("notes") if isinstance(data.get("notes"), list) else [HOSTED_NOTE]
        return cls(
            job_id=str(data["job_id"]),
            name=str(data.get("name") or ""),
            status=str(data.get("status") or "queued"),
            created=str(data.get("created") or ""),
            finished=str(data["finished"]) if data.get("finished") else None,
            audit_id=str(data["audit_id"]) if data.get("audit_id") else None,
            decision=str(data["decision"]) if data.get("decision") else None,
            error=str(data["error"]) if data.get("error") else None,
            progress={e: str(progress.get(e, "queued")) for e in ENGINES},
            notes=[str(n) for n in notes],
        )


Runner = Callable[[Upload], tuple[str, str]]


def offline_runner(settings: Settings, out_dir: Path) -> Runner:
    def run(upload: Upload) -> tuple[str, str]:
        from evalpilot.audit.intake import AuditInputs
        from evalpilot.audit.run import AuditOptions, run_audit

        inputs = AuditInputs(system_card=upload.system_card, traces=upload.traces, trace_version=upload.trace_version,
                             zip_path=upload.code_zip)
        options = AuditOptions(provider="offline", out_dir=out_dir, ai_review=False)
        result = run_audit(settings, inputs, options, on_progress=upload.on_progress)
        _prune(out_dir)
        return result.audit_id, result.verdict.decision

    return run


def admin_runner(settings: Settings, out_dir: Path, provider: str) -> Runner:
    def run(upload: Upload) -> tuple[str, str]:
        from evalpilot.audit.intake import AuditInputs
        from evalpilot.audit.run import AuditOptions, run_audit

        inputs = AuditInputs(target_url=upload.target_url, adapter=upload.adapter, authorized=upload.authorized,
                             system_card=upload.system_card, traces=upload.traces, trace_version=upload.trace_version,
                             repo=upload.repo, zip_path=upload.code_zip, path=upload.path, engines=upload.engines)
        options = AuditOptions(provider=provider, out_dir=out_dir, ai_review=upload.ai_review)
        result = run_audit(settings, inputs, options, on_progress=upload.on_progress)
        return result.audit_id, result.verdict.decision

    return run


def public_runner(settings: Settings, out_dir: Path, provider: str, *, hosted: bool = False) -> Runner:
    """Jobs-mode runner: same inputs as admin (URL/repo/AI review), then prune old upload audits."""
    def run(upload: Upload) -> tuple[str, str]:
        from evalpilot.audit.intake import AuditInputs
        from evalpilot.audit.run import AuditOptions, run_audit

        inputs = AuditInputs(target_url=upload.target_url, adapter=upload.adapter, authorized=upload.authorized,
                             system_card=upload.system_card, traces=upload.traces, trace_version=upload.trace_version,
                             repo=upload.repo, zip_path=upload.code_zip, path=upload.path, engines=upload.engines,
                             hosted=hosted)
        options = AuditOptions(provider=provider, out_dir=out_dir, ai_review=upload.ai_review)
        result = run_audit(settings, inputs, options, on_progress=upload.on_progress)
        _prune(out_dir)
        return result.audit_id, result.verdict.decision

    return run


def _prune(out_dir: Path) -> None:
    audits = sorted((p for p in out_dir.glob("audit-*") if p.is_dir()), key=lambda p: p.name)
    for old in audits[:-KEEP_UPLOAD_AUDITS]:
        shutil.rmtree(old, ignore_errors=True)


class JobQueue:
    def __init__(self, runner: Runner, *, max_queued: int, max_kept: int, inline: bool = False,
                 note: str = HOSTED_NOTE, store: Path | None = None) -> None:
        self.runner = runner
        self.max_kept = max_kept
        self.inline = inline
        self.note = note
        self.store = store
        if store is not None:
            store.mkdir(parents=True, exist_ok=True)
        self.jobs: dict[str, Job] = {}
        self._queue: queue.Queue[tuple[Job, Upload]] = queue.Queue(maxsize=max_queued)
        self._lock = threading.Lock()
        self._worker: threading.Thread | None = None

    def _save(self, job: Job) -> None:
        if self.store is None:
            return
        path = self.store / f"{job.job_id}.json"
        path.write_text(json.dumps(job.to_dict()), encoding="utf-8")

    def _load(self, job_id: str) -> Job | None:
        if self.store is None or not job_id.isalnum() or len(job_id) > 32:
            return None
        path = self.store / f"{job_id}.json"
        if not path.is_file():
            return None
        try:
            job = Job.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
            return None
        if job.status in ("queued", "running"):
            job.status = "failed"
            job.error = "the API restarted before this audit finished; start it again"
            job.finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
            for engine, state in job.progress.items():
                if state in ("queued", "running"):
                    job.progress[engine] = "failed" if state == "running" else "skipped"
            self._save(job)
        with self._lock:
            self.jobs.setdefault(job.job_id, job)
        return job

    def submit(self, upload: Upload, *, name: str = "") -> Job:
        job = Job(job_id=uuid.uuid4().hex[:16], name=name[:80], notes=[self.note])

        def on_progress(engine: str, state: str) -> None:
            job.progress[engine] = state
            self._save(job)

        upload.on_progress = on_progress
        with self._lock:
            self.jobs[job.job_id] = job
            for old in list(self.jobs)[: max(0, len(self.jobs) - self.max_kept)]:
                del self.jobs[old]
        self._save(job)
        if self.inline:
            self._execute(job, upload)
            return job
        try:
            self._queue.put_nowait((job, upload))
        except queue.Full:
            with self._lock:
                self.jobs.pop(job.job_id, None)
            if self.store is not None:
                (self.store / f"{job.job_id}.json").unlink(missing_ok=True)
            if not upload.keep_workdir:
                shutil.rmtree(upload.workdir, ignore_errors=True)
            raise QueueFull("audit queue is full; try again in a minute") from None
        self._ensure_worker()
        return job

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            found = self.jobs.get(job_id)
        return found or self._load(job_id)

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
        self._save(job)
        try:
            job.audit_id, job.decision = self.runner(upload)
            job.status = "done"
        except Exception as exc:  # the worker must survive bad uploads
            from evalpilot.audit.adapters import AdapterError
            from evalpilot.audit.intake import IntakeError
            from evalpilot.llm.budget import BudgetExceeded
            from evalpilot.models import ValidationError

            if isinstance(exc, (IntakeError, ValidationError, ValueError, AdapterError, BudgetExceeded)):
                job.error = str(exc).replace(str(upload.workdir), "<upload>")
            else:
                job.error = "audit failed (internal error)"
            job.status = "failed"
            for engine, state in job.progress.items():
                if state in ("queued", "running"):
                    job.progress[engine] = "failed" if state == "running" else "skipped"
        finally:
            job.finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._save(job)
            if not upload.keep_workdir:
                shutil.rmtree(upload.workdir, ignore_errors=True)
