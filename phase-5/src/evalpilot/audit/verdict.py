"""SHIP / BLOCK from the risk register. Phase 7 also ANDs in the release gate."""

from __future__ import annotations

from evalpilot.audit.models import LEVELS, Risk, Verdict
from evalpilot.config import AuditConfig


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
