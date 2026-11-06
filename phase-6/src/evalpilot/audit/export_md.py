"""Markdown audit report (audit.md). PDF export arrives in Phase 7."""

from __future__ import annotations

from typing import Any

from evalpilot.audit.models import CoverageCell, Risk, Verdict


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render(
    intake: dict[str, Any],
    risks: list[Risk],
    coverage: list[CoverageCell],
    verdict: Verdict,
    flaws: list[dict[str, Any]] | None = None,
) -> str:
    lines: list[str] = []
    add = lines.append
    add(f"# AI System Audit: {intake.get('target', '?')}")
    add("")
    add(f"- Audit id: `{intake.get('audit_id')}`")
    add(f"- Date: {intake.get('finished', intake.get('started', ''))}")
    add(f"- Engines: {', '.join(intake.get('engines', []))}")
    add(f"- Provider: {intake.get('provider')} | spend this audit: ${intake.get('spend_usd', 0):.4f}")
    inputs = {k: v for k, v in intake.get("inputs", {}).items() if v not in (None, False, [], "")}
    add(f"- Inputs: {', '.join(f'{k}={v}' for k, v in inputs.items())}")
    tools = intake.get("tools", {})
    if tools:
        add(f"- Tools: {', '.join(f'{k} {v}' for k, v in tools.items())}")
    add("")

    add(f"## Verdict: **{verdict.decision}**")
    add("")
    for reason in verdict.reasons:
        add(f"- {reason}")
    if verdict.deciding_risks:
        add(f"- Deciding risks: {', '.join(f'`{r}`' for r in verdict.deciding_risks)}")
    counts = verdict.counts
    add(f"- Open risks: {counts.get('critical', 0)} critical, {counts.get('high', 0)} high, "
        f"{counts.get('medium', 0)} medium, {counts.get('low', 0)} low; {counts.get('accepted', 0)} accepted")
    if verdict.conditions:
        add("")
        add("Conditions:")
        for c in verdict.conditions:
            add(f"- {c}")
    add("")

    add("## Risk register")
    add("")
    add("Severity = likelihood x impact (1-5 each). Critical >= 20, High >= 12, Medium >= 6. "
        "Risks backed only by AI review (no rule, tool or probe agrees) are capped at "
        f"{intake.get('ai_only_max_level', 'medium')} until Phase 5 measures review precision.")
    add("")
    if risks:
        add("| Risk | Level | Severity (L x I) | OWASP | Title | Evidence | Status | Fix |")
        add("|---|---|---|---|---|---|---|---|")
        for r in risks:
            level = f"{r.level} (AI-only, capped from {r.capped_from})" if r.capped_from else r.level
            add(f"| `{r.risk_id}` | {level} | {r.severity} ({r.likelihood}x{r.impact}) | {r.owasp or '-'} | {_cell(r.title)} | "
                f"{len(r.evidence)} | {r.status} | {_cell(r.fix)} |")
    else:
        add("No risks found.")
    add("")

    add("## Guardrail coverage map")
    add("")
    add("| Layer | Threats | Declared | Status | Failed checks | Passed checks |")
    add("|---|---|---|---|---|---|")
    for c in coverage:
        add(f"| {c.layer} | {', '.join(c.threats)} | {'yes' if c.declared else 'no'} | **{c.status}** | "
            f"{_cell(', '.join(c.failed_checks[:4])) or '-'} | {len(c.passed_checks)} |")
    add("")

    if flaws:
        found = sum(f["found"] for f in flaws)
        present = sum(f["present"] for f in flaws)
        add("## Planted flaws")
        add("")
        add(f"{found}/{len(flaws)} found with their required detections; {present}/{len(flaws)} still present.")
        add("")
        add("| Flaw | OWASP | Title | Found | Present | Matched checks |")
        add("|---|---|---|---|---|---|")
        for f in flaws:
            add(f"| {f['id']} | {f['owasp']} | {_cell(f['title'])} | {'yes' if f['found'] else 'no'} | "
                f"{'yes' if f['present'] else 'no'} | {_cell(', '.join(f['matched_checks'])) or '-'} |")
        add("")

    add("## Evidence")
    add("")
    for r in risks:
        add(f"### `{r.risk_id}` {r.level.upper()} - {r.title}")
        add("")
        add(f"Checks: {', '.join(f'`{c}`' for c in r.check_ids)}")
        add("")
        for ev in r.evidence:
            add(f"- **{ev.kind}** `{ev.location}`")
            if ev.excerpt:
                add("")
                add("  ```text")
                for line in ev.excerpt.splitlines()[:8]:
                    add(f"  {line}")
                add("  ```")
        add("")
        add(f"Fix: {r.fix}")
        add("")

    notes = intake.get("notes", [])
    if notes:
        add("## Notes")
        add("")
        for n in notes:
            add(f"- {n}")
        add("")
    return "\n".join(lines)
