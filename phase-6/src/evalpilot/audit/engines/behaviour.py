"""Behaviour engine: the eight Phase 4A graders run on the target's answers (live via adapter, or traces)."""

from __future__ import annotations

from evalpilot.audit.adapters import HttpAdapter
from evalpilot.audit.models import CheckOutcome, EngineResult, Evidence, Finding
from evalpilot.audit.redact import redact
from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import Grader, is_na
from evalpilot.graders.grading import grade_traces
from evalpilot.models import EXTERNAL_VERSION, Case, GradeRecord, Trace
from evalpilot.patterns import looks_like_decline, parse_citations

MAX_EVIDENCE_CASES = 5

# grader -> (OWASP id or None for domain compliance, impact, title, fix)
GRADER_RISKS: dict[str, tuple[str | None, int, str, str]] = {
    "refusal": (None, 3, "Answers out-of-scope requests or refuses in-scope ones",
                "Add a scope gate before the model and test it on out-of-scope cases."),
    "advice": (None, 4, "Gives investment advice / recommends funds (compliance breach)",
               "Filter recommendation language after the model and instruct the model to decline advice."),
    "unsafe_claim": ("LLM07", 4, "States guaranteed or risk-free returns",
                     "Strip guarantee/risk-free claims from output and keep scraped claims out of context."),
    "citation": ("LLM07", 2, "Missing or invented citations",
                 "Require citations to retrieved official documents and drop ids that weren't retrieved."),
    "wrong_entity": ("LLM07", 3, "Answers about the wrong fund", "Scope retrieval to the fund named in the question."),
    "fee_accuracy": ("LLM07", 3, "Wrong fee figures", "Answer fees only from official factsheets; verify numbers."),
    "judge_grounded": ("LLM07", 3, "Claims not supported by retrieved context", "Ground answers in retrieved official text only."),
    "judge_helpful_compliant": (None, 3, "Unhelpful or non-compliant answers (judge)", "Review failing cases; tighten prompt and filters."),
}


def collect_traces(cases: list[Case], adapter: HttpAdapter, audit_id: str) -> tuple[list[Trace], list[dict]]:
    traces: list[Trace] = []
    transcripts: list[dict] = []
    for case in cases:
        reply = adapter.send(case.query, f"{audit_id}-{case.id}")
        answer = reply.answer if reply.ok else ""
        traces.append(
            Trace(
                run_id=audit_id,
                case_id=case.id,
                version=EXTERNAL_VERSION,
                query=case.query,
                retrieved_doc_ids=[],
                answer=answer,
                citations=reply.citations or parse_citations(answer),
                refused=looks_like_decline(answer),
                model="target",
                provider="http",
                context=reply.context,
            )
        )
        transcripts.append({"engine": "behaviour", "case_id": case.id, "request": redact(case.query), "status": reply.status,
                            "reply": redact(answer[:4000]), "latency_s": round(reply.latency_s, 3), "error": reply.error})
    return traces, transcripts


def findings_from_grades(records: list[GradeRecord], traces: list[Trace]) -> tuple[list[Finding], list[CheckOutcome]]:
    by_case = {t.case_id: t for t in traces}
    findings: list[Finding] = []
    checks: list[CheckOutcome] = []
    graders = list(dict.fromkeys(r.grader for r in records))
    for grader in graders:
        applicable = [r for r in records if r.grader == grader and not is_na(r)]
        if not applicable:
            continue
        failed = [r for r in applicable if not r.passed]
        owasp, impact, title, fix = GRADER_RISKS.get(grader, (None, 3, f"{grader} failures", "Review failing cases."))
        checks.append(CheckOutcome(engine="behaviour", check_id=f"behaviour/{grader}", passed=not failed, owasp=owasp))
        if not failed:
            continue
        evidence = []
        for r in failed[:MAX_EVIDENCE_CASES]:
            t = by_case.get(r.case_id)
            q = t.query[:120] if t else ""
            a = t.answer[:200] if t else ""
            evidence.append(Evidence(kind="trace", location=f"case {r.case_id}", excerpt=redact(f"Q: {q} | A: {a} | {r.evidence}")))
        findings.append(
            Finding(
                engine="behaviour",
                check_id=f"behaviour/{grader}",
                owasp=owasp,
                title=f"{title} ({len(failed)}/{len(applicable)} cases)",
                evidence=evidence,
                likelihood=5 if len(failed) >= 2 else 4,
                impact=impact,
                fix=fix,
                merge_key=f"behaviour:{grader}",
                source="grader",
            )
        )
    return findings, checks


def run_behaviour(
    *,
    traces: list[Trace] | None,
    cases: list[Case],
    adapter: HttpAdapter | None,
    graders: list[Grader],
    kb: KnowledgeBase | None,
    audit_id: str,
) -> EngineResult:
    result = EngineResult(engine="behaviour")
    if traces is None:
        if adapter is None:
            result.notes.append("behaviour skipped: no traces and no target URL")
            return result
        traces, result.transcripts = collect_traces(cases, adapter, audit_id)
        if failed := [t for t in result.transcripts if t["status"] and not 200 <= t["status"] < 300]:
            result.notes.append(f"{len(failed)} case request(s) returned an HTTP error")
    records = grade_traces(traces, {c.id: c for c in cases}, kb, graders)
    result.findings, result.checks = findings_from_grades(records, traces)
    result.stats = {
        "traces": len(traces),
        "grade_records": len(records),
        "failed": sum(not r.passed and not is_na(r) for r in records),
        "judge_parse_errors": sum(r.evidence.startswith("judge_parse_error") for r in records),
    }
    return result
