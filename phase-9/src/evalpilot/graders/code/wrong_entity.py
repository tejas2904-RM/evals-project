"""wrong_entity: the answer names no fund other than the one the question is about."""

from __future__ import annotations

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import CheckResult, CodeGrader, not_applicable
from evalpilot.models import Case, Trace


def check(case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> CheckResult | str:
    if case is None or not case.gold_entity:
        return not_applicable("no gold entity")
    if kb is None:
        return not_applicable("no knowledge base to resolve fund names")
    named = kb.detect_entities(trace.answer)
    if others := [e for e in named if e != case.gold_entity]:
        return False, f"names {others} instead of / as well as {case.gold_entity}"
    if case.gold_entity in named:
        return True, f"names only {case.gold_entity}"
    return True, "names no other fund"


WRONG_ENTITY = CodeGrader("wrong_entity", check)
