"""Config review: rule checks over the system card and config-like files in the repo."""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass

from evalpilot.audit.files import SourceFile
from evalpilot.audit.models import CheckOutcome, EngineResult, Evidence, Finding
from evalpilot.audit.redact import find_secrets, redact
from evalpilot.audit.system_card import SystemCard

CONFIG_GLOBS = ("*.toml", "*.yaml", "*.yml", "*.json", "*.ini", "*.cfg", ".env*", "Dockerfile", "config.py", "settings.py")
DEBUG_RE = re.compile(r"""^\s*["']?debug["']?\s*[:=]\s*["']?(true|1|yes|on)\b""", re.IGNORECASE)
CORS_RE = re.compile(r"""Access-Control-Allow-Origin["']?\s*[:,]\s*["']\*["']""", re.IGNORECASE)


@dataclass(frozen=True)
class Check:
    id: str
    owasp: str | None
    likelihood: int
    impact: int
    title: str
    fix: str


CHECKS = {
    c.id: c
    for c in (
        Check("cfg-rate-limit", "LLM06", 3, 3, "No per-user rate limit declared", "Declare and enforce a per-user/session rate limit (HTTP 429)."),
        Check("cfg-max-output", "LLM06", 3, 3, "No max output tokens declared", "Set max output tokens for every model and declare it."),
        Check("cfg-model-pinned", "LLM04", 3, 2, "Model not pinned to a snapshot", "Pin a dated model snapshot so behaviour doesn't change under you."),
        Check("cfg-secrets-inline", "LLM02", 4, 5, "Secrets stored inline", "Load secrets from the environment or a secret manager; rotate any exposed key."),
        Check("cfg-log-redaction", "LLM02", 4, 4, "Prompts logged without PII redaction", "Stop logging prompt text or redact PII before logging."),
        Check("cfg-tool-confirmation", "LLM03", 4, 5, "Side-effecting tool runs without confirmation", "Require human confirmation for write/external tools."),
        Check("cfg-untrusted-sources", "LLM05", 3, 4, "Untrusted data source not isolated", "Tag scraped/user content as untrusted and keep it out of answer retrieval."),
        Check("cfg-hidden-context-secrets", "LLM08", 4, 4, "System prompt contains secrets", "Move secrets out of the prompt; assume hidden context can leak."),
        Check("cfg-debug-on", None, 3, 2, "Debug mode enabled in config", "Disable debug in deployed configuration."),
        Check("cfg-cors-wildcard", "LLM10", 3, 3, "CORS allows any origin", "Allow-list the origins that may call the API."),
        Check("cfg-ci-secret-exposure", "LLM04", 4, 5, "pull_request_target workflow exposes secrets to PR code", "Don't check out PR code in pull_request_target jobs that can read secrets."),
        Check("config/unknown_field", None, 1, 1, "Unknown field in system card", "Remove the field or add it to the system card schema."),
    )
}


def _finding(check: Check, evidence: list[Evidence], merge_suffix: str = "", title: str | None = None) -> Finding:
    check_id = check.id if check.id.startswith("config/") else f"config/{check.id}"
    return Finding(
        engine="config",
        check_id=check_id,
        owasp=check.owasp,
        title=title or check.title,
        evidence=evidence,
        likelihood=check.likelihood,
        impact=check.impact,
        fix=check.fix,
        merge_key=f"config:{check.id}{merge_suffix}",
        source="card",
    )


def _ev(location: str, excerpt: str) -> Evidence:
    return Evidence(kind="config_key", location=location, excerpt=redact(excerpt)[:200])


def review_card(card: SystemCard) -> tuple[list[Finding], list[CheckOutcome]]:
    findings: list[Finding] = []
    checks: list[CheckOutcome] = []

    def outcome(check_id: str, failed: list[Evidence], title: str | None = None) -> None:
        check = CHECKS[check_id]
        cid = check_id if check_id.startswith("config/") else f"config/{check_id}"
        checks.append(CheckOutcome(engine="config", check_id=cid, passed=not failed, owasp=check.owasp))
        if failed:
            findings.append(_finding(check, failed, title=title))

    outcome("cfg-rate-limit", [] if card.rate_limits.per_user_rpm else [_ev("card.rate_limits.per_user_rpm", "null")])
    has_cap = card.rate_limits.max_output_tokens or (card.models and all(m.max_tokens for m in card.models))
    outcome("cfg-max-output", [] if has_cap else [_ev("card.rate_limits.max_output_tokens", "null")])
    unpinned = [m for m in card.models if not m.pinned_version]
    outcome("cfg-model-pinned", [_ev(f"card.models[{card.models.index(m)}]", f"{m.name} (pinned_version null)") for m in unpinned])
    outcome("cfg-secrets-inline", [_ev("card.secrets_management", "inline")] if card.secrets_management == "inline" else [])
    log_bad = card.logging.logs_prompts and not card.logging.pii_redaction
    outcome("cfg-log-redaction", [_ev("card.logging", "logs_prompts=true, pii_redaction=false")] if log_bad else [])
    unconfirmed = [
        t for t in card.tools
        if t.side_effects in ("write", "external") and not t.requires_confirmation and t.name not in card.human_in_the_loop
    ]
    outcome(
        "cfg-tool-confirmation",
        [_ev(f"card.tools[{card.tools.index(t)}]", f"{t.name}: side_effects={t.side_effects}, requires_confirmation=false") for t in unconfirmed],
    )
    untrusted = [s for s in card.data_sources if s.type in ("scraped", "user") and not s.tenant_isolation]
    outcome(
        "cfg-untrusted-sources",
        [_ev(f"card.data_sources[{card.data_sources.index(s)}]", f"{s.name}: type={s.type}, isolated=false, ingestion={s.ingestion}") for s in untrusted],
    )
    secrets_in_prompt = card.system_prompt_policy.contains_secrets
    outcome("cfg-hidden-context-secrets", [_ev("card.system_prompt_policy.contains_secrets", "true")] if secrets_in_prompt else [])
    for name in card.unknown_fields():
        findings.append(_finding(CHECKS["config/unknown_field"], [_ev(f"card.{name}", "unknown field")], merge_suffix=f":{name}",
                                 title=f"Unknown field '{name}' in system card"))
    return findings, checks


def _is_config_file(file: SourceFile) -> bool:
    return any(fnmatch.fnmatch(file.name, g) for g in CONFIG_GLOBS) or file.rel.startswith(".github/workflows/")


def review_files(files: list[SourceFile]) -> tuple[list[Finding], list[CheckOutcome]]:
    findings: list[Finding] = []
    configs = [f for f in files if _is_config_file(f)]

    def line_hits(candidates: list[SourceFile], pattern: re.Pattern[str]) -> list[tuple[SourceFile, int, str]]:
        return [(f, i, line) for f in candidates for i, line in enumerate(f.lines, start=1) if pattern.search(line)]

    debug = line_hits(configs, DEBUG_RE)
    for file, lineno, line in debug:
        findings.append(_finding(CHECKS["cfg-debug-on"], [Evidence(kind="file_line", location=f"{file.rel}:{lineno}", excerpt=redact(line.strip()))],
                                 merge_suffix=f":{file.rel}"))
    cors = line_hits(files, CORS_RE)
    for file, lineno, line in cors:
        findings.append(_finding(CHECKS["cfg-cors-wildcard"], [Evidence(kind="file_line", location=f"{file.rel}:{lineno}", excerpt=redact(line.strip()))],
                                 merge_suffix=f":{file.rel}"))
    secret_hits = 0
    for file in configs:
        for lineno, line in enumerate(file.lines, start=1):
            if find_secrets(line):
                secret_hits += 1
                f = _finding(CHECKS["cfg-secrets-inline"], [Evidence(kind="file_line", location=f"{file.rel}:{lineno}", excerpt=redact(line.strip())[:200])],
                             title="Key-shaped secret in a config file")
                findings.append(f.model_copy(update={"merge_key": f"secret:{file.rel}"}))
    workflows = [f for f in files if f.rel.startswith(".github/workflows/")]
    ci_exposed = 0
    for wf in workflows:
        if "pull_request_target" in wf.text and "secrets." in wf.text and "actions/checkout" in wf.text:
            ci_exposed += 1
            findings.append(_finding(CHECKS["cfg-ci-secret-exposure"], [Evidence(kind="file_line", location=f"{wf.rel}:1", excerpt="pull_request_target + checkout + secrets")],
                                     merge_suffix=f":{wf.rel}"))

    checks: list[CheckOutcome] = []
    if configs:
        checks.append(CheckOutcome(engine="config", check_id="config/cfg-debug-on", passed=not debug))
        checks.append(CheckOutcome(engine="config", check_id="config/cfg-secrets-inline", passed=not secret_hits, owasp="LLM02"))
    if files:
        checks.append(CheckOutcome(engine="config", check_id="config/cfg-cors-wildcard", passed=not cors, owasp="LLM10"))
    if workflows:
        checks.append(CheckOutcome(engine="config", check_id="config/cfg-ci-secret-exposure", passed=not ci_exposed, owasp="LLM04"))
    return findings, checks


def run_config_review(card: SystemCard | None, files: list[SourceFile]) -> EngineResult:
    result = EngineResult(engine="config")
    if card is not None:
        f, c = review_card(card)
        result.findings += f
        result.checks += c
    else:
        result.notes.append("no system card: card checks skipped")
    if files:
        f, c = review_files(files)
        result.findings += f
        result.checks += c
    return result
