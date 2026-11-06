"""fee_accuracy: every gold fee number appears in the answer (within 0.01)."""

from __future__ import annotations

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import CheckResult, CodeGrader, not_applicable
from evalpilot.models import Case, Trace
from evalpilot.patterns import extract_numbers

TOLERANCE = 0.01


def check(case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> CheckResult | str:
    if case is None or not case.gold_fee:
        return not_applicable("no gold fee")
    numbers = extract_numbers(trace.answer)
    missing = {k: v for k, v in case.gold_fee.items() if not any(abs(n - v) <= TOLERANCE for n in numbers)}
    if missing:
        found = ", ".join(f"{n:g}" for n in numbers) or "none"
        return False, f"expected {missing}; numbers in answer: {found}"
    return True, f"all gold values present {case.gold_fee}"


FEE_ACCURACY = CodeGrader("fee_accuracy", check)
