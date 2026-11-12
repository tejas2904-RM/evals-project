"""Derived numbers the web screens show. Everything here is computed from the report context or audit files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evalpilot.config import Settings

# A case is a critical failure when it fails a grader the gate requires at (nearly) 100%.
CRITICAL_MIN_RATE = 0.95
GUARDRAIL_STATES = ("present", "weak", "missing", "n/a")
FOUND_BY = {"probe": "Security test", "grader": "Eval grader", "rule": "Code rule", "tool": "Code scanner",
            "card": "Config review", "ai": "AI code review"}


def critical_graders(settings: Settings) -> list[str]:
    return sorted(g for g, rate in settings.gate.min_pass_rate.items() if rate >= CRITICAL_MIN_RATE)


def case_status(trace: dict[str, Any], critical: list[str]) -> dict[str, Any]:
    applicable = {g: r for g, r in trace["grades"].items() if not r["na"]}
    failing = sorted(g for g, r in applicable.items() if not r["passed"])
    return {"passed": not failing and bool(applicable), "failing": failing,
            "critical": any(g in critical for g in failing)}


def version_summaries(ctx: dict[str, Any], critical: list[str]) -> dict[str, dict[str, Any]]:
    """`fixed_cases`: now pass every check and didn't before. `regressed_cases`: worse on any grader (the gate's rule)."""
    out: dict[str, dict[str, Any]] = {}
    passed_by: dict[str, set[str]] = {}
    for v in ctx["versions"]:
        statuses = [(c["id"], case_status(c["versions"][v], critical)) for c in ctx["cases"] if v in c["versions"]]
        passed_by[v] = {cid for cid, s in statuses if s["passed"]}
        compare = next((c for c in ctx["compares"] if c["candidate"] == v), None)
        base = compare["baseline"] if compare else None
        fixed = sorted(passed_by[v] - passed_by.get(base, set())) if base else []
        regressed = sorted({cid for d in (compare or {}).get("graders", {}).values() for cid in d["regressed"]})
        out[v] = {
            "version": v,
            "cases_total": len(statuses),
            "cases_passed": sum(s["passed"] for _, s in statuses),
            "critical_failures": sum(s["critical"] for _, s in statuses),
            "critical_case_ids": [cid for cid, s in statuses if s["critical"]],
            "baseline": base,
            "fixed_cases": fixed,
            "regressed_cases": regressed,
            "gate": ctx["gates"][v]["verdict"],
        }
    return out


def judges_trusted(calibration: dict[str, Any], judges: list[str]) -> list[dict[str, Any]]:
    out = []
    for name in judges:
        g = calibration["graders"][name]
        out.append({"judge": name, "trusted": bool(g["enough_labels"] and g["meets_targets"]),
                    "n_labels": g["n_labels"], "min_labels": g["min_labels"],
                    "labels_needed": max(0, g["min_labels"] - g["n_labels"]), "kappa": g["kappa"]})
    return out


def bot_costs(run_path: Path) -> dict[str, float]:
    costs: dict[str, float] = {}
    traces = run_path / "traces.jsonl"
    if traces.is_file():
        for line in traces.read_text(encoding="utf-8").splitlines():
            if line.strip():
                t = json.loads(line)
                costs[t["version"]] = costs.get(t["version"], 0.0) + float(t.get("cost_usd") or 0.0)
    return {v: round(c, 6) for v, c in costs.items()}


def guardrail_state(cell: dict[str, Any]) -> str:
    status = cell["status"]
    if status == "verified":
        return "present"
    if status == "declared":
        return "weak"
    if status == "failed":
        return "weak" if cell.get("passed_checks") else "missing"
    return "n/a" if status == "n/a" else "missing"


def guardrails(coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for cell in coverage:
        state = guardrail_state(cell)
        if cell["status"] == "verified":
            detail = f"{len(cell['passed_checks'])} passing check(s)"
        elif cell["status"] == "declared":
            detail = "declared in the system card, not yet tested"
        elif cell["status"] == "failed":
            detail = f"{len(cell['failed_checks'])} failing check(s)"
        elif cell["status"] == "n/a":
            detail = "no tools with side effects"
        else:
            detail = "not declared and no evidence found"
        out.append({"layer": cell["layer"], "state": state, "detail": detail, "threats": cell["threats"],
                    "declared": cell["declared"], "passed_checks": cell["passed_checks"],
                    "failed_checks": cell["failed_checks"]})
    return out


def _findings(path: Path) -> dict[str, dict[str, Any]]:
    file = path / "findings.jsonl"
    if not file.is_file():
        return {}
    rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {r["finding_id"]: r for r in rows}


def audit_stats(path: Path, intake: dict[str, Any]) -> dict[str, Any]:
    stats = intake.get("engine_stats") or {}
    behaviour, security, code = stats.get("behaviour") or {}, stats.get("security") or {}, stats.get("code") or {}
    findings = _findings(path).values()
    records, failed = behaviour.get("grade_records"), behaviour.get("failed")
    return {
        "quality_pct": round(100 * (records - failed) / records) if records else None,
        "behaviour_records": records,
        "behaviour_failed": failed,
        "security_passed": security.get("pass") if security else None,
        "security_total": security.get("probes") if security else None,
        "code_findings": sum(f["engine"] == "code" for f in findings) if "code" in (intake.get("engines") or []) else None,
        "files_scanned": code.get("files_scanned"),
    }


def found_by(path: Path, risks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings = _findings(path)
    out = []
    for r in risks:
        sources = sorted({FOUND_BY.get(findings[f]["source"], findings[f]["source"]) for f in r["findings"] if f in findings})
        out.append({**r, "found_by": sources})
    return out


def input_kinds(intake: dict[str, Any]) -> list[str]:
    inputs = intake.get("inputs") or {}
    kinds = []
    if inputs.get("target_url"):
        kinds.append("bot URL")
    if inputs.get("system_card"):
        kinds.append("system card")
    if inputs.get("traces"):
        kinds.append("traces")
    if inputs.get("repo"):
        kinds.append("GitHub repo")
    elif inputs.get("zip_path") or inputs.get("path"):
        kinds.append("code")
    return kinds


def headline(verdict: dict[str, Any]) -> str:
    counts = verdict.get("counts", {})
    if verdict["decision"] == "SHIP":
        return "Ship it: no blocking risks"
    blocking = [(counts.get(level, 0), level) for level in ("critical", "high") if counts.get(level)]
    if not blocking:
        return "Blocked"
    parts = " and ".join(f"{n} {level}" for n, level in blocking)
    return f"Blocked: {parts} risk{'s' if sum(n for n, _ in blocking) > 1 else ''} need{'' if sum(n for n, _ in blocking) > 1 else 's'} fixing"
