"""FastAPI app: read-only views over runs/reference/, public hosted jobs (Phase 10), and owner-only admin mode.

Start with `uvicorn evalpilot.api.app:create_app --factory` (Render) or `evalpilot serve [--admin]` (local).
"""

from __future__ import annotations

import hmac
import json
import re
import shutil
import tempfile
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import httpx
from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from evalpilot import VERSIONS, __version__
from evalpilot.api import admin as admin_ops
from evalpilot.api.jobs import (ADMIN_NOTE, HOSTED_JOBS_NOTE, HOSTED_NOTE, PUBLIC_NOTE, JobQueue, QueueFull, Upload,
                                admin_runner, offline_runner, public_runner)
from evalpilot.api.repository import STATUSES, NotFound, Repository
from evalpilot.api.settings import ApiSettings, assert_keyless, jobs_provider
from evalpilot.audit.adapters import AdapterError
from evalpilot.audit.intake import IntakeError, assert_hosted_probe_url, parse_repo_url
from evalpilot.audit.models import ENGINES
from evalpilot.audit.redact import redact
from evalpilot.config import ConfigError, Settings, load_settings
from evalpilot.graders import GRADER_NAMES
from evalpilot.graders.llm import JUDGE_NAMES
from evalpilot.llm import Ledger
from evalpilot.llm.budget import BudgetExceeded
from evalpilot.models import ValidationError

VERSION_RE = re.compile(r"^v\d+$")
MAX_PAGE = 100
UPLOAD_FIELDS = {"traces": "traces.jsonl", "system_card": "system_card.json", "code_zip": "code.zip"}
DEMO_BOT = "Asterion FAQ bot (demo)"
ADMIN_OFF = "admin mode is off: run `evalpilot serve --admin` on your own machine"
INPUT_KINDS = ("url", "card", "code", "traces")


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


def _csv(value: str | None, allowed: tuple[str, ...], what: str) -> list[str]:
    items = [v.strip() for v in (value or "").split(",") if v.strip()]
    bad = [v for v in items if v not in allowed]
    if bad:
        raise HTTPException(400, f"unknown {what}: {', '.join(bad)} (expected {', '.join(allowed)})")
    return items


def _flag(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


def create_app(settings: Settings | None = None, api: ApiSettings | None = None, *, inline_jobs: bool = False,
               target_client: httpx.Client | None = None) -> FastAPI:
    api = api or ApiSettings.from_env()
    settings = settings or load_settings()
    assert_keyless(api)
    repo = Repository(settings, local_audits=api.admin)
    provider = jobs_provider(api)
    if api.admin:
        runner = admin_runner(settings, settings.runs_dir, api.admin_provider)
        note, ledger_path = ADMIN_NOTE, settings.ledger_path
    elif api.jobs_enabled:
        runner = public_runner(settings, repo.uploads, provider, hosted=api.hosted)
        note = PUBLIC_NOTE if provider != "offline" else HOSTED_JOBS_NOTE
        ledger_path = settings.ledger_path if provider != "offline" else repo.reference / "spend.jsonl"
    else:
        runner = offline_runner(settings, repo.uploads)
        note, ledger_path = HOSTED_NOTE, repo.reference / "spend.jsonl"
    jobs = JobQueue(runner, max_queued=api.max_queued_jobs, max_kept=api.max_kept_jobs, inline=inline_jobs, note=note)
    limiter = RateLimiter(api.post_per_minute)
    play_limiter = RateLimiter(60)
    spend_ledger = Ledger(ledger_path)
    admin_inputs = settings.runs_dir / "admin-inputs"

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
        allow_headers=["Content-Type", "Authorization"],
        allow_credentials=False,
        max_age=600,
    )

    def client_ip(request: Request) -> str:
        if api.trust_forwarded_for and (fwd := request.headers.get("x-forwarded-for")):
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def is_admin(request: Request) -> bool:
        if not api.admin:
            return False
        header = request.headers.get("authorization", "")
        token = header[7:] if header.lower().startswith("bearer ") else ""
        return bool(token) and hmac.compare_digest(token.encode(), (api.admin_token or "").encode())

    def require_admin(request: Request) -> None:
        if not api.admin:
            raise HTTPException(403, ADMIN_OFF)
        if not is_admin(request):
            raise HTTPException(401, "admin token missing or wrong (it is printed by `evalpilot serve --admin`)")

    @app.exception_handler(NotFound)
    async def not_found(_request: Request, exc: NotFound):
        return RedactedJSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(IntakeError)
    @app.exception_handler(ValidationError)
    @app.exception_handler(ConfigError)
    @app.exception_handler(AdapterError)
    @app.exception_handler(ValueError)
    async def bad_input(_request: Request, exc: Exception):
        return RedactedJSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(BudgetExceeded)
    async def over_budget(_request: Request, exc: BudgetExceeded):
        return RedactedJSONResponse({"detail": str(exc)}, status_code=402)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, "mode": "admin" if api.admin else api.mode,
                "hosted": api.hosted, "reference_runs": repo.run_ids()}

    @app.get("/api/meta")
    def meta() -> dict[str, Any]:
        spent = spend_ledger.total()
        return {"version": __version__, "mode": "admin" if api.admin else api.mode, "admin": api.admin,
                "hosted": api.hosted, "jobs_enabled": api.jobs_enabled,
                "provider": provider,
                "max_upload_mb": api.max_upload_bytes // (1024 * 1024), "versions": list(VERSIONS),
                "graders": list(GRADER_NAMES), "judges": list(JUDGE_NAMES), "engines": list(ENGINES),
                "runs": repo.run_ids(), "bots": [{"run_id": r, "name": DEMO_BOT} for r in repo.run_ids()[:1]],
                "budget": {"budget_usd": settings.budget_usd, "spent_usd": round(spent, 4),
                           "remaining_usd": round(max(0.0, settings.budget_usd - spent), 4)}}

    @app.get("/api/admin/session")
    def admin_session(request: Request) -> dict[str, Any]:
        require_admin(request)
        return {"admin": True, "provider": api.admin_provider}

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
        status: str | None = None,
        q: Annotated[str | None, Query(max_length=200)] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 20,
    ) -> dict[str, Any]:
        if case_version:
            _version(case_version)
        if failing and failing not in GRADER_NAMES:
            raise HTTPException(400, f"unknown grader '{failing}'")
        if status and status not in STATUSES:
            raise HTTPException(400, f"unknown status '{status}' (expected {', '.join(STATUSES)})")
        return repo.cases(run_id, _version(version), category=category, case_version=case_version, failing=failing,
                          q=q, offset=offset, limit=limit, status=status)

    @app.get("/api/verdict")
    def verdict(version: str = "v3", run: str | None = None) -> dict[str, Any]:
        run_ids = repo.run_ids()
        if not run_ids:
            raise NotFound("no reference runs")
        return repo.context(run or run_ids[0], _version(version))["final"]

    @app.get("/api/estimate")
    def estimate(engines: str | None = None, inputs: str | None = None, ai_review: str | None = None) -> dict[str, Any]:
        chosen = _csv(engines, ENGINES, "engine") or list(ENGINES)
        kinds = _csv(inputs, INPUT_KINDS, "input")
        n_cases = sum(1 for line in settings.cases_path.read_text(encoding="utf-8").splitlines() if line.strip())
        return admin_ops.estimate(settings, spend_ledger, provider=provider, engines=chosen, inputs=kinds,
                                  ai_review=(api.admin or api.jobs_enabled) and _flag(ai_review), n_cases=n_cases)

    @app.post("/api/playground")
    def playground(request: Request, body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        if not play_limiter.allow(client_ip(request)):
            raise HTTPException(429, "too many playground questions; try again in a minute")
        versions = body.get("versions") or ["v1", "v3"]
        if not isinstance(versions, list) or not 1 <= len(versions) <= 3:
            raise HTTPException(400, "versions must be a list of 1-3 versions")
        versions = [_version(str(v)) for v in versions]
        if body.get("case_id"):
            run_id = str(body.get("run") or (repo.run_ids() or [""])[0])
            return repo.reference_answers(run_id, str(body["case_id"]), versions)
        if not body.get("question"):
            raise HTTPException(400, "send case_id (a reference question) or question (admin mode)")
        require_admin(request)
        return admin_ops.playground_live(settings, api.admin_provider, str(body["question"]), versions)

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

    async def _save_files(upload: Upload, files: dict[str, UploadFile]) -> None:
        budget = api.max_upload_bytes
        for name, f in files.items():
            data = await f.read(budget + 1)
            budget -= len(data)
            if budget < 0:
                raise HTTPException(413, "upload too large")
            target = upload.workdir / UPLOAD_FIELDS[name]
            target.write_bytes(data)
            setattr(upload, name, target)

    @app.post("/api/audits", status_code=202)
    async def submit_audit(
        request: Request,
        traces: Annotated[UploadFile | None, File()] = None,
        system_card: Annotated[UploadFile | None, File()] = None,
        code_zip: Annotated[UploadFile | None, File()] = None,
        trace_version: Annotated[str | None, Form()] = None,
        system_card_json: Annotated[str | None, Form(max_length=200_000)] = None,
        name: Annotated[str | None, Form(max_length=80)] = None,
        engines: Annotated[str | None, Form()] = None,
        target_url: Annotated[str | None, Form(max_length=2000)] = None,
        request_body: Annotated[str | None, Form(max_length=4000)] = None,
        answer_path: Annotated[str | None, Form(max_length=200)] = None,
        authorized: Annotated[str | None, Form()] = None,
        repo_url: Annotated[str | None, Form(alias="repo", max_length=300)] = None,
        ai_review: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        if not api.jobs_enabled:
            raise HTTPException(403, "this API is read-only (EVALPILOT_API_MODE=readonly)")
        admin = is_admin(request)
        if api.admin and not admin:
            require_admin(request)
        if not admin and not limiter.allow(client_ip(request)):
            raise HTTPException(429, "too many audit submissions; try again in a minute")
        files = {n: f for n, f in (("traces", traces), ("system_card", system_card), ("code_zip", code_zip)) if f}
        if system_card and system_card_json:
            raise HTTPException(400, "send the system card as a file or as JSON text, not both")
        if not files and not system_card_json and not target_url and not repo_url:
            raise HTTPException(400, "add at least one input: bot URL, system card, code or traces")
        if trace_version:
            _version(trace_version)
        chosen = _csv(engines, ENGINES, "engine") or None
        target = None
        if target_url:
            if not _flag(authorized):
                raise HTTPException(400, "tick 'I own this bot or have written permission to test it' to probe a URL")
            target = admin_ops.parse_target(target_url, request_body or "", answer_path or "")
            if api.hosted:
                assert_hosted_probe_url(target.url)
        if repo_url:
            parse_repo_url(repo_url.strip(), "main")
        if system_card_json:
            try:
                json.loads(system_card_json)
            except json.JSONDecodeError as exc:
                raise HTTPException(400, f"system card is not valid JSON ({exc.msg})") from exc
        if admin:
            workdir = admin_inputs / uuid.uuid4().hex[:16]
            workdir.mkdir(parents=True)
        else:
            workdir = Path(tempfile.mkdtemp(prefix="evalpilot-upload-"))
        upload = Upload(workdir=workdir, trace_version=trace_version or None, engines=chosen, keep_workdir=admin)
        try:
            await _save_files(upload, files)
            written = admin_ops.write_inputs(workdir, target, system_card_json)
            upload.system_card = written.get("system_card", upload.system_card)
            if target is not None:
                upload.target_url, upload.adapter, upload.authorized = target.url, written["adapter"], True
            upload.repo = repo_url or None
            upload.ai_review = (admin or api.jobs_enabled) and _flag(ai_review)
            job = jobs.submit(upload, name=name or "")
        except QueueFull as exc:
            shutil.rmtree(workdir, ignore_errors=True)
            raise HTTPException(503, str(exc)) from exc
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
        return job.to_dict()

    @app.post("/api/audits/{audit_id}/rerun", status_code=202)
    def rerun(request: Request, audit_id: str) -> dict[str, Any]:
        require_admin(request)
        path, source = repo.audit_path(audit_id)
        if source != "local":
            raise HTTPException(409, "only audits created on this machine can be re-run")
        inputs = json.loads((path / "intake.json").read_text(encoding="utf-8")).get("inputs") or {}

        def p(key: str) -> Path | None:
            return Path(inputs[key]) if inputs.get(key) else None

        missing = [k for k in ("adapter", "system_card", "traces", "zip_path", "path") if p(k) and not p(k).exists()]
        if missing:
            raise HTTPException(409, f"inputs no longer on disk ({', '.join(missing)}); start a new audit")
        upload = Upload(workdir=Path(tempfile.mkdtemp(prefix="evalpilot-rerun-")), target_url=inputs.get("target_url"),
                        adapter=p("adapter"), authorized=bool(inputs.get("authorized")), system_card=p("system_card"),
                        traces=p("traces"), trace_version=inputs.get("trace_version"), repo=inputs.get("repo"),
                        code_zip=p("zip_path"), path=p("path"), engines=inputs.get("engines"),
                        ai_review=bool(json.loads((path / "intake.json").read_text(encoding="utf-8"))
                                       .get("engine_stats", {}).get("code", {}).get("ai_review")))
        try:
            job = jobs.submit(upload, name=f"Re-run of {audit_id}")
        except QueueFull as exc:
            raise HTTPException(503, str(exc)) from exc
        return job.to_dict()

    @app.post("/api/connection-test")
    def connection_test(request: Request, body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        admin = is_admin(request)
        if not api.jobs_enabled:
            raise HTTPException(403, ADMIN_OFF)
        if api.admin and not admin:
            require_admin(request)
        if not admin and not limiter.allow(client_ip(request)):
            raise HTTPException(429, "too many requests; try again in a minute")
        if body.get("authorized") is not True:
            raise HTTPException(400, "tick 'I own this bot or have written permission to test it' first")
        target = admin_ops.parse_target(str(body.get("url") or ""), str(body.get("request_body") or ""),
                                        str(body.get("answer_path") or ""))
        if api.hosted:
            assert_hosted_probe_url(target.url)
        return admin_ops.connection_test(target, timeout_s=settings.audit.request_timeout_s, client=target_client)

    @app.post("/api/system-card/draft")
    async def draft_card(
        request: Request,
        code_zip: Annotated[UploadFile | None, File()] = None,
        repo_url: Annotated[str | None, Form(alias="repo", max_length=300)] = None,
    ) -> dict[str, Any]:
        from evalpilot.audit.card_draft import draft_card as draft
        from evalpilot.audit.files import iter_text_files
        from evalpilot.audit.intake import AuditInputs, prepare

        admin = is_admin(request)
        if not admin and not api.jobs_enabled:
            raise HTTPException(403, ADMIN_OFF)
        if api.admin and not admin:
            require_admin(request)
        if not code_zip and not repo_url:
            raise HTTPException(400, "upload a .zip or give a public GitHub repo")
        if not admin and not limiter.allow(client_ip(request)):
            raise HTTPException(429, "too many requests; try again in a minute")
        workdir = Path(tempfile.mkdtemp(prefix="evalpilot-draft-"))
        try:
            zip_path = None
            if code_zip:
                data = await code_zip.read(api.max_upload_bytes + 1)
                if len(data) > api.max_upload_bytes:
                    raise HTTPException(413, "upload too large")
                zip_path = workdir / "code.zip"
                zip_path.write_bytes(data)
            intake = prepare(AuditInputs(zip_path=zip_path, repo=repo_url or None, engines=["code"]), settings.audit,
                             audit_id="draft", default_cases=settings.cases_path)
            try:
                cfg = settings.audit
                files = iter_text_files(intake.code_root, max_files=cfg.max_files, max_file_bytes=cfg.max_file_kb * 1024)
                return draft(files, fallback_name=intake.target_name)
            finally:
                intake.cleanup()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    @app.post("/api/labels")
    def add_label(request: Request, body: Annotated[dict[str, Any], Body()]) -> dict[str, Any]:
        from evalpilot.labeling import LabelStore
        from evalpilot.models import Label

        require_admin(request)
        run_id, case_id = str(body.get("run_id") or ""), str(body.get("case_id") or "")
        version, grader = _version(str(body.get("version") or "")), str(body.get("grader") or "")
        if grader not in GRADER_NAMES:
            raise HTTPException(400, f"unknown grader '{grader}'")
        if not isinstance(body.get("human_pass"), bool):
            raise HTTPException(400, "human_pass must be true or false")
        case = next((c for c in repo.context(run_id, version)["cases"] if c["id"] == case_id), None)
        if case is None or version not in case["versions"]:
            raise NotFound(f"case '{case_id}' ({version}) not found in run '{run_id}'")
        label = Label(case_id=case_id, version=version, grader=grader, human_pass=body["human_pass"], labeler="owner",
                      ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), run_id=run_id,
                      note=str(body.get("note") or "")[:500])
        created = LabelStore(settings.labels_path).upsert(label)
        repo.clear_cache()
        return {"saved": True, "created": created, "label": label.to_dict()}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict[str, Any]:
        found = jobs.get(job_id)
        if found is None:
            raise NotFound(f"job '{job_id}' not found")
        return found.to_dict()

    return app
