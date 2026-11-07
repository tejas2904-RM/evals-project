"""Load example-bot audits (vulnerable / fixed) for AI-review precision."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalpilot.audit.flaws import FIXES_FILE, PLANTED_FILE, PlantedFlaw, load_planted, planted_file_for
from evalpilot.audit.models import Finding
from evalpilot.audit.run import resolve_audit


@dataclass(frozen=True)
class ExampleAudit:
    audit_id: str
    variant: str  # "vulnerable" | "fixed"
    provider: str
    findings: list[Finding]
    flaws: list[PlantedFlaw]
    ai_stats: dict[str, Any]


def _variant_and_flaws(intake: dict[str, Any], root: Path) -> tuple[str, Path] | None:
    code_path = (intake.get("inputs") or {}).get("path")
    if code_path:
        code_root = (root / code_path).resolve()
        planted = planted_file_for(code_root)
        if planted is not None:
            return ("vulnerable" if (code_root / PLANTED_FILE).is_file() else "fixed", planted)
        if (code_root / FIXES_FILE).is_file():
            return None
    recorded = intake.get("planted_flaws_file")
    if recorded and Path(recorded).is_file():
        return ("vulnerable" if "vulnerable" in intake.get("audit_id", "") else "fixed", Path(recorded))
    return None


def load_example_audit(path: Path, root: Path) -> ExampleAudit | None:
    """None when the audit isn't of an example bot with a planted-flaw answer key."""
    intake = json.loads((path / "intake.json").read_text(encoding="utf-8"))
    found = _variant_and_flaws(intake, root)
    if found is None:
        return None
    variant, planted = found
    findings_path = path / "findings.jsonl"
    findings = []
    if findings_path.is_file():
        for line in findings_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                findings.append(Finding.model_validate_json(line))
    stats = ((intake.get("engine_stats") or {}).get("code") or {}).get("ai_review") or {}
    return ExampleAudit(
        audit_id=intake.get("audit_id", path.name),
        variant=variant,
        provider=intake.get("provider", ""),
        findings=findings,
        flaws=load_planted(planted),
        ai_stats=stats,
    )


def resolve_example_audits(runs_dir: Path, root: Path, refs: list[str]) -> list[ExampleAudit]:
    """Explicit refs, or the latest audit of each variant that ran the AI review."""
    if refs:
        loaded = [load_example_audit(resolve_audit(runs_dir, ref), root) for ref in refs]
        return [a for a in loaded if a is not None]
    latest: dict[str, ExampleAudit] = {}
    for path in sorted(runs_dir.glob("audit-*")):
        if not (path / "intake.json").is_file():
            continue
        audit = load_example_audit(path, root)
        if audit is not None and audit.ai_stats.get("calls"):
            latest[audit.variant] = audit
    return [latest[v] for v in ("vulnerable", "fixed") if v in latest]
