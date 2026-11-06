"""Run a full audit: intake -> engines -> coverage -> risk register -> verdict -> runs/audit-<id>/."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from evalpilot import __version__
from evalpilot.audit import ai_review
from evalpilot.audit.adapters import HttpAdapter
from evalpilot.audit.coverage import build_coverage, declared_vs_observed
from evalpilot.audit.engines.behaviour import run_behaviour
from evalpilot.audit.engines.code_scan import run_code_scan
from evalpilot.audit.engines.config_review import run_config_review
from evalpilot.audit.engines.security import load_probes, run_security
from evalpilot.audit.export_md import render
from evalpilot.audit.files import SourceFile, iter_text_files
from evalpilot.audit.flaws import evaluate, load_planted, planted_file_for
from evalpilot.audit.intake import AuditInputs, Intake, prepare
from evalpilot.audit.models import CheckOutcome, CoverageCell, EngineResult, Finding, Risk, Verdict
from evalpilot.audit.redact import redact
from evalpilot.audit.risk import build_register, load_acceptances, number_findings
from evalpilot.audit.verdict import decide
from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.config import Settings
from evalpilot.data import load_corpus
from evalpilot.graders import code_graders, llm_graders
from evalpilot.llm import Ledger, LlmClient
from evalpilot.models import Trace

FILES = ("intake.json", "transcripts.jsonl", "findings.jsonl", "risk_register.json", "coverage.json", "verdict.json", "audit.md")


@dataclass
class AuditOptions:
    provider: str
    out_dir: Path | None = None
    acceptances: Path | None = None
    ai_review: bool | None = None
    max_probes: int | None = None
    rate_per_s: float | None = None
    today: date | None = None


@dataclass
class AuditResult:
    audit_id: str
    out_dir: Path
    findings: list[Finding]
    risks: list[Risk]
    coverage: list[CoverageCell]
    verdict: Verdict
    intake: dict[str, Any]
    flaws: list[dict[str, Any]] | None = None
    engine_stats: dict[str, Any] = field(default_factory=dict)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "target"


def new_audit_dir(runs_dir: Path, target: str) -> tuple[str, Path]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"audit-{stamp}-{_slug(target)}"
    audit_id, n = base, 2
    while (runs_dir / audit_id).exists():
        audit_id, n = f"{base}-{n}", n + 1
    path = runs_dir / audit_id
    path.mkdir(parents=True)
    return audit_id, path


def _write(path: Path, text: str) -> None:
    path.write_text(redact(text), encoding="utf-8", newline="\n")


def _jsonl(rows: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows)


def _knowledge_base(settings: Settings) -> KnowledgeBase | None:
    try:
        return KnowledgeBase(load_corpus(settings.corpus_dir))
    except (OSError, ValueError):
        return None


def run_audit(
    settings: Settings,
    inputs: AuditInputs,
    options: AuditOptions,
    *,
    http_client: httpx.Client | None = None,
    adapter_client: httpx.Client | None = None,
) -> AuditResult:
    cfg = settings.audit
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pending_id = "audit-pending"
    intake: Intake = prepare(inputs, cfg, audit_id=pending_id, default_cases=settings.cases_path, http_client=http_client)
    runs_root = options.out_dir or settings.runs_dir
    runs_root.mkdir(parents=True, exist_ok=True)
    audit_id, out = new_audit_dir(runs_root, intake.target_name)
    if intake.traces:
        intake.traces = [Trace.from_dict({**t.to_dict(), "run_id": audit_id}) if t.run_id == pending_id else t
                         for t in intake.traces]

    client = LlmClient(settings, options.provider)
    adapter: HttpAdapter | None = None
    results: list[EngineResult] = []
    files: list[SourceFile] = []
    try:
        if inputs.target_url and intake.adapter:
            rate = options.rate_per_s or intake.adapter.rate_per_s or cfg.probe_rate_per_s
            timeout = intake.adapter.timeout_s or cfg.request_timeout_s
            adapter = HttpAdapter(inputs.target_url, intake.adapter, rate_per_s=rate, timeout_s=timeout, client=adapter_client)
        if intake.code_root is not None:
            files = iter_text_files(intake.code_root, max_files=cfg.max_files, max_file_bytes=cfg.max_file_kb * 1024)

        if "behaviour" in intake.engines:
            graders = code_graders() + llm_graders(client, settings.judge_prompts_path, audit_id)
            results.append(run_behaviour(traces=intake.traces, cases=intake.cases, adapter=adapter, graders=graders,
                                         kb=_knowledge_base(settings), audit_id=audit_id))
        if "security" in intake.engines and adapter is not None:
            probes = load_probes(settings.data_dir / "probes" / "owasp_llm_2026.jsonl")
            results.append(run_security(probes, adapter, intake.card, client, audit_id=audit_id,
                                        max_requests=options.max_probes or cfg.max_probes))
        if "code" in intake.engines and intake.code_root is not None:
            code = run_code_scan(intake.code_root, files, gitleaks_bin=cfg.gitleaks_bin)
            results.append(code)
            if options.ai_review if options.ai_review is not None else cfg.ai_review:
                review = ai_review.review(files, code.stats.get("hit_files", []), client, audit_id=audit_id,
                                          max_files=cfg.ai_review_max_files, max_input_tokens=cfg.ai_review_max_input_tokens,
                                          max_completion_tokens=cfg.ai_review_max_completion_tokens)
                review.findings = ai_review.corroborate(review.findings, code.findings)
                code.findings += review.findings
                code.notes += review.notes
                code.stats.update(review.stats)
        if "config" in intake.engines:
            results.append(run_config_review(intake.card, files))
    finally:
        if adapter is not None:
            adapter.close()
        planted_path = planted_file_for(intake.code_root)
        planted = load_planted(planted_path) if planted_path else None
        intake.cleanup()

    checks: list[CheckOutcome] = [c for r in results for c in r.checks]
    coverage = build_coverage(checks, intake.card)
    findings = [f for r in results for f in r.findings] + declared_vs_observed(coverage)
    findings = number_findings(findings)
    risks = build_register(findings, cfg, load_acceptances(options.acceptances), options.today)
    verdict = decide(risks, cfg)

    flaws = [r.model_dump() for r in evaluate(planted, findings)] if planted is not None else None

    spend = Ledger(settings.ledger_path).total(audit_id)
    notes = intake.notes + [n for r in results for n in r.notes]
    tools: dict[str, str] = {}
    for r in results:
        tools.update(r.stats.get("tools", {}))
    intake_doc: dict[str, Any] = {
        "audit_id": audit_id,
        "evalpilot_version": __version__,
        "target": intake.target_name,
        "inputs": {k: str(v) if isinstance(v, Path) else v for k, v in asdict(inputs).items()},
        "engines": intake.engines,
        "provider": options.provider,
        "cases_source": intake.cases_source,
        "hashes": intake.hashes,
        "tools": tools,
        "engine_stats": {r.engine: r.stats for r in results},
        "notes": notes,
        "started": started,
        "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "spend_usd": round(spend, 6),
        "planted_flaws_file": str(planted_path) if planted_path else None,
        "ai_only_max_level": cfg.ai_only_max_level,
    }

    _write(out / "intake.json", json.dumps(intake_doc, indent=2, ensure_ascii=False))
    _write(out / "transcripts.jsonl", _jsonl([t for r in results for t in r.transcripts]))
    _write(out / "findings.jsonl", _jsonl([f.model_dump() for f in findings]))
    _write(out / "risk_register.json", json.dumps([r.model_dump() for r in risks], indent=2, ensure_ascii=False))
    _write(out / "coverage.json", json.dumps([c.model_dump() for c in coverage], indent=2, ensure_ascii=False))
    _write(out / "verdict.json", json.dumps(verdict.model_dump(), indent=2, ensure_ascii=False))
    if flaws is not None:
        _write(out / "flaws.json", json.dumps(flaws, indent=2, ensure_ascii=False))
    _write(out / "audit.md", render(intake_doc, risks, coverage, verdict, flaws))

    return AuditResult(audit_id=audit_id, out_dir=out, findings=findings, risks=risks, coverage=coverage,
                       verdict=verdict, intake=intake_doc, flaws=flaws, engine_stats=intake_doc["engine_stats"])


def load_audit(path: Path) -> tuple[dict[str, Any], list[Risk], list[CoverageCell], Verdict, list[dict[str, Any]] | None]:
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    risks = [Risk.model_validate(r) for r in json.loads((path / "risk_register.json").read_text(encoding="utf-8"))]
    coverage = [CoverageCell.model_validate(c) for c in json.loads((path / "coverage.json").read_text(encoding="utf-8"))]
    verdict = Verdict.model_validate_json((path / "verdict.json").read_text(encoding="utf-8"))
    flaws_path = path / "flaws.json"
    flaws = json.loads(flaws_path.read_text(encoding="utf-8")) if flaws_path.is_file() else None
    return intake, risks, coverage, verdict, flaws


def resolve_audit(runs_dir: Path, ref: str) -> Path:
    """An audit id under runs/, or a path to an audit directory."""
    candidate = Path(ref)
    if (candidate / "risk_register.json").is_file():
        return candidate
    if (runs_dir / ref / "risk_register.json").is_file():
        return runs_dir / ref
    raise FileNotFoundError(f"no audit found for '{ref}' (looked in {runs_dir})")
