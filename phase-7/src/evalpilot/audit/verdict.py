"""SHIP / BLOCK from the risk register, and the final verdict: release gate AND audit."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from evalpilot.audit.models import LEVELS, Risk, Verdict
from evalpilot.config import AuditConfig


class FinalVerdict(BaseModel):
    decision: str  # "SHIP" | "BLOCK"
    version: str
    run_id: str
    audit_id: str | None
    gate_verdict: str  # "PASS" | "BLOCKED"
    audit_decision: str | None  # "SHIP" | "BLOCK" | None (no audit)
    deciding_rules: list[str]
    deciding_risks: list[str]
    reasons: list[str]
    conditions: list[str]


def final_decision(
    gate: dict[str, Any], audit: Verdict | None, *, version: str, run_id: str, audit_id: str | None
) -> FinalVerdict:
    """SHIP only when the release gate passes AND the audit says SHIP. A missing audit blocks."""
    rules = [
        f"{v['grader']} | {v['rule']} | {v['threshold']} | {v['observed']} | {', '.join(v['case_ids']) or '-'}"
        for v in gate.get("violations", [])
    ]
    reasons = []
    if gate["verdict"] != "PASS":
        reasons.append(f"release gate {version}: BLOCKED ({len(rules)} violation(s))")
    else:
        reasons.append(f"release gate {version}: PASS")
    if audit is None:
        reasons.append("no audit of this version: run `evalpilot audit --traces ... --trace-version` first")
    else:
        reasons.append(f"audit {audit_id}: {audit.decision} ({'; '.join(audit.reasons)})")
    ship = gate["verdict"] == "PASS" and audit is not None and audit.decision == "SHIP"
    return FinalVerdict(
        decision="SHIP" if ship else "BLOCK",
        version=version,
        run_id=run_id,
        audit_id=audit_id,
        gate_verdict=gate["verdict"],
        audit_decision=audit.decision if audit else None,
        deciding_rules=rules,
        deciding_risks=list(audit.deciding_risks) if audit else [],
        reasons=reasons,
        conditions=list(audit.conditions) if audit else [],
    )


def decide(risks: list[Risk], cfg: AuditConfig) -> Verdict:
    open_risks = [r for r in risks if r.status == "open"]
    critical = [r for r in open_risks if r.level == "critical"]
    high = [r for r in open_risks if r.level == "high"]
    medium = [r for r in open_risks if r.level == "medium"]

    deciding: list[str] = []
    reasons: list[str] = []
    if cfg.block_on_critical and critical:
        deciding += [r.risk_id for r in critical]
        reasons.append(f"{len(critical)} open critical risk(s)")
    if len(high) > cfg.max_open_high:
        deciding += [r.risk_id for r in high]
        reasons.append(f"{len(high)} open high risk(s) > max_open_high={cfg.max_open_high}")

    conditions = [
        f"{r.risk_id} (medium{f', AI-only, capped from {r.capped_from}' if r.capped_from else ''}, {r.severity}): {r.title}"
        " - fix, or accept with an owner and expiry"
        for r in medium
    ]
    conditions += [
        f"{r.risk_id} accepted by {r.acceptance['owner']} until {r.acceptance['expires']}"
        for r in risks
        if r.status == "accepted" and r.acceptance
    ]
    counts = {level: sum(r.level == level for r in open_risks) for level in LEVELS}
    counts["accepted"] = sum(r.status == "accepted" for r in risks)
    if not reasons:
        reasons.append("no open critical risks and open high risks within max_open_high")
    return Verdict(
        decision="BLOCK" if deciding else "SHIP",
        deciding_risks=deciding,
        reasons=reasons,
        conditions=conditions,
        counts=counts,
    )
