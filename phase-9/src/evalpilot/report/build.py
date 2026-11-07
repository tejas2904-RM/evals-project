"""Collect a run, its gates/compares/calibration, audits and spend into one report context.

The report is a view: every number is recomputed from traces, grades, labels, audits and the ledger.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from evalpilot import VERSIONS, __version__
from evalpilot.audit.intake import sha256_file
from evalpilot.audit.models import Verdict
from evalpilot.audit.verdict import final_decision
from evalpilot.compare import default_baseline, diff_grades, evaluate_gate, for_version
from evalpilot.config import Settings
from evalpilot.data import load_dataset
from evalpilot.graders import GRADER_NAMES, is_na
from evalpilot.graders.grading import load_grades, load_traces
from evalpilot.graders.llm import JUDGE_NAMES
from evalpilot.labeling import LabelStore, calibrate
from evalpilot.llm import Ledger

HARD_CEILING_USD = 5.00
V2_OVER_V1 = ("refusal", "advice", "unsafe_claim", "citation")


@dataclass(frozen=True)
class Sources:
    run_path: Path
    audit_paths: list[Path]
    ledger_path: Path
    labels_path: Path
    version: str = "v3"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def audit_role(intake: dict[str, Any]) -> str:
    code_path = str((intake.get("inputs") or {}).get("path") or "").replace("\\", "/").rstrip("/")
    if code_path.endswith("vulnerable_bot"):
        return "vulnerable"
    if code_path.endswith("fixed_bot"):
        return "fixed"
    return "other"


def find_bot_audit(audit_paths: list[Path], run_path: Path, version: str) -> Path | None:
    """The latest audit whose traces are exactly this run's traces.jsonl, filtered to `version`."""
    want = sha256_file(run_path / "traces.jsonl")
    matches = []
    for path in audit_paths:
        intake = _json(path / "intake.json")
        if intake.get("hashes", {}).get("traces") == want and intake.get("inputs", {}).get("trace_version") == version:
            matches.append(path)
    return max(matches, key=lambda p: p.name) if matches else None


def audit_dirs(*roots: Path) -> list[Path]:
    found = []
    for root in roots:
        if root.is_dir():
            found += [p for p in root.glob("audit-*") if (p / "risk_register.json").is_file() and (p / "verdict.json").is_file()]
    return sorted(found, key=lambda p: p.name)


def select_audits(audit_paths: list[Path], run_path: Path, version: str) -> list[Path]:
    """This version's own-bot audit plus the latest vulnerable and fixed example audits."""
    picked: dict[str, Path] = {}
    for path in audit_paths:
        role = audit_role(_json(path / "intake.json"))
        if role in ("vulnerable", "fixed") and (role not in picked or path.name > picked[role].name):
            picked[role] = path
    bot = find_bot_audit(audit_paths, run_path, version)
    return sorted({*picked.values(), *([bot] if bot else [])}, key=lambda p: p.name)


def audit_summary(path: Path, role: str) -> dict[str, Any]:
    intake = _json(path / "intake.json")
    verdict = _json(path / "verdict.json")
    flaws = _json(path / "flaws.json") if (path / "flaws.json").is_file() else None
    return {
        "audit_id": intake.get("audit_id", path.name),
        "role": role,
        "target": intake.get("target", "?"),
        "provider": intake.get("provider"),
        "finished": intake.get("finished"),
        "engines": intake.get("engines", []),
        "spend_usd": intake.get("spend_usd", 0.0),
        "verdict": verdict,
        "risks": _json(path / "risk_register.json"),
        "coverage": _json(path / "coverage.json"),
        "flaws": flaws,
        "exports": sorted(p.name for p in path.iterdir() if p.suffix in (".md", ".pdf")),
        "notes": intake.get("notes", []),
    }


def _spend(ledger_path: Path, budget: float) -> dict[str, Any]:
    entries = Ledger(ledger_path).entries()
    by_model: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0})
    by_purpose: dict[str, dict[str, float]] = defaultdict(lambda: {"calls": 0, "cost_usd": 0.0})
    for e in entries:
        for table, key in ((by_model, e.model), (by_purpose, e.purpose)):
            table[key]["calls"] += 1
            table[key]["cost_usd"] += e.cost_usd
    total = sum(e.cost_usd for e in entries)
    return {
        "total_usd": total,
        "budget_usd": budget,
        "hard_ceiling_usd": HARD_CEILING_USD,
        "calls": len(entries),
        "by_model": dict(sorted(by_model.items())),
        "by_purpose": dict(sorted(by_purpose.items())),
        "last_ts": max((e.ts for e in entries), default=None),
        "judge_models": sorted({e.model for e in entries if e.purpose == "judge"}),
    }


def _matrix(grades: list, versions: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    table: dict[str, dict[str, dict[str, Any]]] = {}
    for grader in GRADER_NAMES:
        row = {}
        for v in versions:
            records = [g for g in grades if g.grader == grader and g.version == v]
            applicable = [g for g in records if not is_na(g)]
            passed = sum(g.passed for g in applicable)
            row[v] = {"passed": passed, "applicable": len(applicable), "na": len(records) - len(applicable),
                      "rate": passed / len(applicable) if applicable else None}
        table[grader] = row
    return table


def _cases(dataset, traces, grades, versions) -> list[dict[str, Any]]:
    by_trace = {(t.case_id, t.version): t for t in traces}
    by_grade: dict[tuple[str, str], dict[str, Any]] = defaultdict(dict)
    for g in grades:
        by_grade[(g.case_id, g.version)][g.grader] = {"passed": g.passed, "na": is_na(g), "evidence": g.evidence}
    out = []
    for case in dataset.cases:
        per_version = {}
        for v in versions:
            t = by_trace.get((case.id, v))
            if t is None:
                continue
            per_version[v] = {
                "answer": t.answer, "citations": t.citations, "retrieved": t.retrieved_doc_ids,
                "refused": t.refused, "guardrails": t.guardrails, "cached": t.cached,
                "grades": by_grade.get((case.id, v), {}),
            }
        out.append({"id": case.id, "category": case.category, "query": case.query, "in_scope": case.in_scope,
                    "should_refuse": case.should_refuse, "versions": per_version})
    return out


def _dod(ctx: dict[str, Any]) -> list[dict[str, str]]:
    m, gates, versions = ctx["matrix"], ctx["gates"], ctx["versions"]
    rows = []

    def add(item: str, status: str, evidence: str) -> None:
        rows.append({"item": item, "status": status, "evidence": evidence})

    if {"v1", "v2"} <= set(versions):
        better = {g: (m[g]["v1"]["passed"], m[g]["v2"]["passed"]) for g in V2_OVER_V1}
        add("v2 beats v1 on refusal, advice, unsafe_claim and citation",
            "pass" if all(b > a for a, b in better.values()) else "fail",
            "; ".join(f"{g} {a} -> {b}" for g, (a, b) in better.items()))
    if {"v2", "v3"} <= set(versions):
        we2, we3 = m["wrong_entity"]["v2"], m["wrong_entity"]["v3"]
        ceiling = we2["applicable"] and we2["passed"] == we2["applicable"] and we3["passed"] == we3["applicable"]
        cmp = next(c for c in ctx["compares"] if c["baseline"] == "v2" and c["candidate"] == "v3")
        regressions = {g: d["regressed"] for g, d in cmp["graders"].items() if d["regressed"]}
        improved = we3["passed"] > we2["passed"] or ceiling
        ok = improved and not regressions
        evidence = f"wrong_entity {we2['passed']}/{we2['applicable']} -> {we3['passed']}/{we3['applicable']}"
        evidence += " (both perfect: ceiling)" if ceiling else ""
        evidence += "; regressions: " + ("; ".join(f"{g}: {', '.join(c)}" for g, c in regressions.items()) or "none")
        add("v3 beats v2 on wrong_entity with no regressions", "pass" if ok else "fail", evidence)
    if "v1" in gates and "v3" in gates:
        v1_blocked = gates["v1"]["verdict"] == "BLOCKED"
        v3 = gates["v3"]
        if v1_blocked and v3["verdict"] == "PASS":
            status, why = "pass", "v1 BLOCKED, v3 PASS"
        elif v1_blocked:
            status = "explained"
            why = "v1 BLOCKED; v3 BLOCKED by: " + "; ".join(
                f"{v['grader']} {v['rule']} ({', '.join(v['case_ids'])})" for v in v3["violations"])
        else:
            status, why = "fail", "v1 passes the gate"
        add("v1 fails the gate; v3 passes, or the report says exactly why", status, why)
    cal = ctx["calibration"]
    judge_counts = ", ".join(f"{n} {cal['graders'][n]['n_labels']}" for n in JUDGE_NAMES)
    add(f"Both judges calibrated on {cal['min_labels']}+ human labels",
        "pass" if cal["enough_labels"] else "pending", f"labels: {judge_counts} (owner action)")
    vuln = [a for a in ctx["audits"] if a["role"] == "vulnerable"]
    fixed = [a for a in ctx["audits"] if a["role"] == "fixed"]
    if vuln and fixed:
        fv, ff = vuln[-1]["flaws"] or [], fixed[-1]["flaws"] or []
        found = sum(f["found"] for f in fv)
        present = sum(f["present"] for f in ff)
        ok = (fv and found == len(fv) and vuln[-1]["verdict"]["decision"] == "BLOCK"
              and ff and present == 0 and fixed[-1]["verdict"]["decision"] == "SHIP")
        add("Every planted flaw found in vulnerable_bot (BLOCK) and closed in fixed_bot (SHIP)",
            "pass" if ok else "fail",
            f"vulnerable {found}/{len(fv)} found, {vuln[-1]['verdict']['decision']}; "
            f"fixed {present}/{len(ff)} present, {fixed[-1]['verdict']['decision']}")
        exports = all({"audit.md", "audit.pdf"} <= set(a["exports"]) for a in (vuln[-1], fixed[-1]))
        add("Audit exported as Markdown and PDF", "pass" if exports else "fail",
            "; ".join(f"{a['audit_id']}: {', '.join(a['exports'])}" for a in (vuln[-1], fixed[-1])))
    s = ctx["spend"]
    add(f"Total OpenAI spend under ${s['hard_ceiling_usd']:.0f}", "pass" if s["total_usd"] < s["hard_ceiling_usd"] else "fail",
        f"${s['total_usd']:.4f} over {s['calls']} paid calls (budget guard ${s['budget_usd']:.2f})")
    final = ctx["final"]
    add("Final verdict = release gate AND audit", "pass" if final["audit_id"] else "fail",
        f"{final['decision']}: " + "; ".join(final["reasons"]))
    return rows


def build_context(settings: Settings, src: Sources) -> dict[str, Any]:
    run_path = src.run_path
    dataset = load_dataset(settings.cases_path, settings.corpus_dir)
    traces = load_traces(run_path)
    grades = load_grades(run_path)
    meta = _json(run_path / "meta.json") if (run_path / "meta.json").is_file() else {}
    versions = [v for v in VERSIONS if any(t.version == v for t in traces)]
    if src.version not in versions:
        raise ValueError(f"version {src.version} not in run {run_path.name} (has {', '.join(versions)})")

    gates = {}
    for v in versions:
        base = default_baseline(v)
        gates[v] = evaluate_gate(grades, v, settings.gate, baseline=base if base in versions else None).to_dict()
    compares = []
    for a, b in zip(versions, versions[1:]):
        compares.append(diff_grades(for_version(grades, a), for_version(grades, b), baseline_label=a, candidate_label=b).to_dict())

    labels = LabelStore(src.labels_path).all()
    calibration = calibrate(labels, grades, settings.calibration, run_id=run_path.name)

    bot_audit = find_bot_audit(src.audit_paths, run_path, src.version)
    audits = []
    for path in sorted(src.audit_paths, key=lambda p: p.name):
        intake = _json(path / "intake.json")
        role = "bot" if path == bot_audit else audit_role(intake)
        audits.append(audit_summary(path, role))
    bot_verdict = Verdict.model_validate(_json(bot_audit / "verdict.json")) if bot_audit else None
    final = final_decision(gates[src.version], bot_verdict, version=src.version, run_id=run_path.name,
                           audit_id=bot_audit.name if bot_audit else None).model_dump()

    spend = _spend(src.ledger_path, settings.budget_usd)
    stamps = [meta.get("finished"), spend["last_ts"], *(a["finished"] for a in audits)]
    ctx: dict[str, Any] = {
        "meta": {
            "evalpilot_version": __version__,
            "run_id": run_path.name,
            "provider": meta.get("provider", traces[0].provider if traces else "?"),
            "bot_model": meta.get("bot_model", traces[0].model if traces else "?"),
            "judge_model": ", ".join(spend["judge_models"]) or settings.judge_model,
            "n_cases": len(dataset.cases),
            # Deterministic: the newest input timestamp, so regenerating unchanged data gives the same file.
            "as_of": max((s for s in stamps if s), default=""),
        },
        "versions": versions,
        "graders": list(GRADER_NAMES),
        "judges": list(JUDGE_NAMES),
        "matrix": _matrix(grades, versions),
        "gates": gates,
        "compares": compares,
        "calibration": calibration,
        "cases": _cases(dataset, traces, grades, versions),
        "legend": {
            "cache_hits": sum(t.cached for t in traces),
            "traces": len(traces),
            "judge_parse_errors": sum(g.evidence.startswith("judge_parse_error") for g in grades),
        },
        "audits": audits,
        "final": final,
        "spend": spend,
    }
    ctx["dod"] = _dod(ctx)
    return ctx
