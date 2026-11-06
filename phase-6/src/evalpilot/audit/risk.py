"""Risk engine: merge findings by root cause, score severity = likelihood x impact, apply acceptances."""

from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from evalpilot.audit.models import LEVELS, Evidence, Finding, Level, Risk, risk_id_for
from evalpilot.config import AuditConfig

MAX_EVIDENCE_PER_RISK = 10


class AcceptanceError(ValueError):
    pass


def level_for(severity: int, cfg: AuditConfig) -> Level:
    if severity >= cfg.severity_critical:
        return "critical"
    if severity >= cfg.severity_high:
        return "high"
    if severity >= cfg.severity_medium:
        return "medium"
    return "low"


def load_acceptances(path: Path | None) -> dict[str, dict[str, str]]:
    """risk_acceptances.toml: [[accept]] risk_id, owner, reason, expires (YYYY-MM-DD)."""
    if path is None:
        return {}
    with path.open("rb") as fh:
        raw = tomllib.load(fh)
    out: dict[str, dict[str, str]] = {}
    for i, row in enumerate(raw.get("accept", []), start=1):
        missing = [k for k in ("risk_id", "owner", "reason", "expires") if not row.get(k)]
        if missing:
            raise AcceptanceError(f"{path.name}: accept #{i} missing {missing}")
        expires = row["expires"]
        if isinstance(expires, str):
            expires = date.fromisoformat(expires)
        out[row["risk_id"]] = {"owner": str(row["owner"]), "reason": str(row["reason"]), "expires": expires.isoformat()}
    return out


def _dedupe(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple[str, str]] = set()
    out: list[Evidence] = []
    for ev in evidence:
        key = (ev.kind, ev.location)
        if key not in seen:
            seen.add(key)
            out.append(ev)
    return out[:MAX_EVIDENCE_PER_RISK]


def number_findings(findings: list[Finding]) -> list[Finding]:
    return [f.model_copy(update={"finding_id": f"F-{i:03d}"}) for i, f in enumerate(findings, start=1)]


def build_register(
    findings: list[Finding],
    cfg: AuditConfig,
    acceptances: dict[str, dict[str, str]] | None = None,
    today: date | None = None,
) -> list[Risk]:
    groups: dict[str, list[Finding]] = {}
    for finding in findings:
        groups.setdefault(finding.merge_key, []).append(finding)

    today = today or date.today()
    acceptances = acceptances or {}
    risks: list[Risk] = []
    for merge_key, group in groups.items():
        worst = max(group, key=lambda f: (f.likelihood * f.impact, f.impact))
        likelihood = max(f.likelihood for f in group)
        sources = {f.source for f in group}
        if "ai" in sources and len(sources) > 1:
            likelihood = min(5, likelihood + 1)
        impact = max(f.impact for f in group)
        severity = likelihood * impact
        risk_id = risk_id_for(merge_key)
        level = level_for(severity, cfg)
        capped_from = None
        cap = cfg.ai_only_max_level
        if sources == {"ai"} and LEVELS.index(level) < LEVELS.index(cap):
            level, capped_from = cap, level
        status, acceptance = "open", None
        if (acc := acceptances.get(risk_id)) and date.fromisoformat(acc["expires"]) >= today:
            status, acceptance = "accepted", acc
        risks.append(
            Risk(
                risk_id=risk_id,
                owasp=next((f.owasp for f in group if f.owasp), None),
                title=worst.title,
                findings=[f.finding_id for f in group],
                check_ids=sorted({f.check_id for f in group}),
                evidence=_dedupe([ev for f in group for ev in f.evidence]),
                likelihood=likelihood,
                impact=impact,
                severity=severity,
                level=level,
                fix=worst.fix,
                status=status,
                acceptance=acceptance,
                capped_from=capped_from,
            )
        )
    return sorted(risks, key=lambda r: (-r.severity, -r.impact, r.risk_id))
