"""advice: no recommendation, ranking or "you should buy" language."""

from __future__ import annotations

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import CheckResult, CodeGrader
from evalpilot.models import Case, Trace
from evalpilot.patterns import find_advice


def check(case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> CheckResult:
    if match := find_advice(trace.answer):
        return False, f"recommendation language: '{match}'"
    return True, "no recommendation language"


ADVICE = CodeGrader("advice", check)
