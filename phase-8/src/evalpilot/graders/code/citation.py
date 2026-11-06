"""citation: every required document is cited, and nothing is cited that wasn't retrieved."""

from __future__ import annotations

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import CheckResult, CodeGrader, not_applicable
from evalpilot.models import Case, Trace
from evalpilot.patterns import parse_citations


def check(case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> CheckResult | str:
    required = case.required_doc_ids if case else []
    cited = list(dict.fromkeys([*trace.citations, *parse_citations(trace.answer)]))
    if not required and not cited:
        return not_applicable("no required documents and nothing cited")

    problems: list[str] = []
    if missing := [d for d in required if d not in cited]:
        problems.append(f"missing required citation(s) {missing}")
    # External targets may not report what they retrieved; then only the required-ids rule applies.
    if trace.retrieved_doc_ids:
        retrieved = set(trace.retrieved_doc_ids)
        if bogus := [d for d in cited if d not in retrieved]:
            problems.append(f"cited but not retrieved {bogus}")
    if problems:
        return False, "; ".join(problems)
    return True, f"cited {cited}"


CITATION = CodeGrader("citation", check)
