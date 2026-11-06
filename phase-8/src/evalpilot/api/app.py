"""FastAPI app: read-only views over runs/reference/ plus optional offline audit jobs.

Start with `uvicorn evalpilot.api.app:create_app --factory` (Render) or `evalpilot serve` (local).
"""

from __future__ import annotations

import json
import re
import tempfile
import threading
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from evalpilot import VERSIONS, __version__
from evalpilot.api.jobs import JobQueue, QueueFull, Upload, offline_runner
from evalpilot.api.repository import NotFound, Repository
from evalpilot.api.settings import ApiSettings, assert_keyless
from evalpilot.audit.intake import IntakeError
from evalpilot.audit.redact import redact
from evalpilot.config import ConfigError, Settings, load_settings
from evalpilot.graders import GRADER_NAMES
from evalpilot.graders.llm import JUDGE_NAMES
from evalpilot.models import ValidationError

VERSION_RE = re.compile(r"^v\d+$")
MAX_PAGE = 100
UPLOAD_FIELDS = {"traces": "traces.jsonl", "system_card": "system_card.json", "code_zip": "code.zip"}


class RedactedJSONResponse(JSONResponse):
    """Every JSON body passes through the audit redactor, so no response can carry a key."""

    def render(self, content: Any) -> bytes:
        return redact(json.dumps(content, ensure_ascii=False, separators=(",", ":"))).encode("utf-8")


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque[float]] = defaultdict(deque)
        self.lock = threading.Lock()

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        with self.lock:
            window = self.hits[key]
            while window and now - window[0] > 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return False
            window.append(now)
            return True


def _version(value: str) -> str:
    if not VERSION_RE.match(value) or value not in VERSIONS:
        raise HTTPException(400, f"unknown version '{value}' (expected one of {', '.join(VERSIONS)})")
    return value


def create_app(settings: Settings | None = None, api: ApiSettings | None = None, *, inline_jobs: bool = False) -> FastAPI:
    api = api or ApiSettings.from_env()
    settings = settings or load_settings()
    assert_keyless(api)
    repo = Repository(settings)
    jobs = JobQueue(offline_runner(settings, repo.uploads), max_queued=api.max_queued_jobs,
                    max_kept=api.max_kept_jobs, inline=inline_jobs)
    limiter = RateLimiter(api.post_per_minute)

    app = FastAPI(title="EvalPilot API", version=__version__, default_response_class=RedactedJSONResponse,
                  description="Read-only views of EvalPilot runs, release gates, calibration, audits and final verdicts.")
    app.state.repo, app.state.jobs, app.state.api = repo, jobs, api

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is None or not length.isdigit():
                return RedactedJSONResponse({"detail": "Content-Length required"}, status_code=411)
            if int(length) > api.max_upload_bytes + 64 * 1024:
                return RedactedJSONResponse({"detail": "upload too large"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # Added last so it wraps everything, including the guard's 411/413 replies.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(api.allowed_origins),
        allow_origin_regex=api.allowed_origin_regex,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
        max_age=600,
    )

    def client_ip(request: Request) -> str:
        if api.trust_forwarded_for and (fwd := request.headers.get("x-forwarded-for")):
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    @app.exception_handler(NotFound)
    async def not_found(_request: Request, exc: NotFound):
        return RedactedJSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(IntakeError)
    @app.exception_handler(ValidationError)
    @app.exception_handler(ConfigError)
    @app.exception_handler(ValueError)
    async def bad_input(_request: Request, exc: Exception):
        return RedactedJSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "mode": api.mode, "hosted": api.hosted,
                "reference_runs": repo.run_ids()}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        return {"version": __version__, "mode": api.mode, "jobs_enabled": api.jobs_enabled,
                "max_upload_mb": api.max_upload_bytes // (1024 * 1024), "versions": list(VERSIONS),
                "graders": list(GRADER_NAMES), "judges": list(JUDGE_NAMES), "runs": repo.run_ids()}

    @app.get("/api/runs")
    def runs() -> list[dict[str, Any]]:
        return repo.run_list()

    @app.get("/api/runs/{run_id}")
    def run(run_id: str, version: str = "v3") -> dict[str, Any]:
        return repo.run_summary(run_id, _version(version))

    @app.get("/api/runs/{run_id}/cases")
    def cases(
        run_id: str,
        version: str = "v3",
        category: str | None = None,
        case_version: Annotated[str | None, Query(alias="case_version")] = None,
        failing: str | None = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
    ) -> dict[str, Any]:
        if case_version:
            _version(case_version)
        if failing and failing not in GRADER_NAMES:
            raise HTTPException(400, f"unknown grader '{failing}'")
        return repo.cases(run_id, _version(version), category=category, case_version=case_version, failing=failing,
                          q=q, offset=offset, limit=limit)

    @app.get("/api/verdict")
    def verdict(version: str = "v3", run: str | None = None) -> dict[str, Any]:
        run_ids = repo.run_ids()
        if not run_ids:
            raise NotFound("no reference runs")
        return repo.context(run or run_ids[0], _version(version))["final"]

    @app.get("/api/audits")
    def audits() -> list[dict[str, Any]]:
        return repo.audit_list()

    @app.get("/api/audits/{audit_id}")
    def audit(audit_id: str) -> dict[str, Any]:
        return repo.audit(audit_id)

    @app.get("/api/audits/{audit_id}/export.{fmt}")
    def export(audit_id: str, fmt: str) -> Response:
        from evalpilot.audit.export_md import render
        from evalpilot.audit.run import load_audit

        if fmt not in ("md", "pdf"):
            raise HTTPException(404, "export format must be md or pdf")
        path, _source = repo.audit_path(audit_id)
        loaded = load_audit(path)
        disposition = {"Content-Disposition": f'attachment; filename="{audit_id}.{fmt}"'}
        if fmt == "md":
            return Response(redact(render(*loaded)), media_type="text/markdown; charset=utf-8", headers=disposition)
        from evalpilot.audit.export_pdf import PdfUnavailable, render_pdf

        try:
            return Response(render_pdf(*loaded), media_type="application/pdf", headers=disposition)
        except PdfUnavailable as exc:
            raise HTTPException(501, str(exc)) from exc

    @app.post("/api/audits", status_code=202)
    async def submit_audit(
        request: Request,
        traces: Annotated[UploadFile | None, File()] = None,
        system_card: Annotated[UploadFile | None, File()] = None,
        code_zip: Annotated[UploadFile | None, File()] = None,
        trace_version: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        if not api.jobs_enabled:
            raise HTTPException(403, "this API is read-only (EVALPILOT_API_MODE=readonly)")
        if not limiter.allow(client_ip(request)):
            raise HTTPException(429, "too many audit submissions; try again in a minute")
        files = {name: f for name, f in (("traces", traces), ("system_card", system_card), ("code_zip", code_zip)) if f}
        if not files:
            raise HTTPException(400, "upload at least one of: traces, system_card, code_zip")
        if trace_version:
            _version(trace_version)
        workdir = Path(tempfile.mkdtemp(prefix="evalpilot-upload-"))
        upload = Upload(workdir=workdir, trace_version=trace_version or None)
        budget = api.max_upload_bytes
        try:
            for name, f in files.items():
                data = await f.read(budget + 1)
                budget -= len(data)
                if budget < 0:
                    raise HTTPException(413, "upload too large")
                target = workdir / UPLOAD_FIELDS[name]
                target.write_bytes(data)
                setattr(upload, name, target)
            job = jobs.submit(upload)
        except QueueFull as exc:
            raise HTTPException(503, str(exc)) from exc
        except BaseException:
            import shutil

            shutil.rmtree(workdir, ignore_errors=True)
            raise
        return job.to_dict()

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        found = jobs.get(job_id)
        if found is None:
            raise NotFound(f"job '{job_id}' not found")
        return found.to_dict()

    return app
