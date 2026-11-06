"""Compare two audits: which risks closed, which are new, which planted flaws went open -> closed."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from evalpilot.audit.models import Risk


@dataclass
class AuditDiff:
    closed: list[Risk] = field(default_factory=list)
    new: list[Risk] = field(default_factory=list)
    still_open: list[tuple[Risk, Risk]] = field(default_factory=list)
    flaws: list[dict[str, Any]] = field(default_factory=list)


def diff_audits(
    risks_a: list[Risk],
    risks_b: list[Risk],
    flaws_a: list[dict[str, Any]] | None = None,
    flaws_b: list[dict[str, Any]] | None = None,
) -> AuditDiff:
    open_a = {r.risk_id: r for r in risks_a if r.status != "closed"}
    open_b = {r.risk_id: r for r in risks_b if r.status != "closed"}
    result = AuditDiff(
        closed=[r for rid, r in open_a.items() if rid not in open_b],
        new=[r for rid, r in open_b.items() if rid not in open_a],
        still_open=[(open_a[rid], open_b[rid]) for rid in open_a if rid in open_b],
    )
    if flaws_a is not None and flaws_b is not None:
        b_by_id = {f["id"]: f for f in flaws_b}
        for fa in flaws_a:
            fb = b_by_id.get(fa["id"])
            before = "open" if fa["present"] else "closed"
            after = "open" if fb and fb["present"] else "closed"
            result.flaws.append({"id": fa["id"], "title": fa["title"], "before": before, "after": after})
    return result
