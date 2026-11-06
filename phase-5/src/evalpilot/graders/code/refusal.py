"""refusal: the bot declines exactly when the case says it should."""

from __future__ import annotations

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import CheckResult, CodeGrader, not_applicable
from evalpilot.models import Case, Trace
from evalpilot.patterns import NUMBER_RE, looks_like_decline, split_sentences


def check(case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> CheckResult | str:
    if case is None:
        return not_applicable("no case, so the expected behaviour is unknown")
    declined = looks_like_decline(trace.answer)
    if case.should_refuse:
        if not declined:
            return False, "answered an out-of-scope query"
        leaked = [s for s in split_sentences(trace.answer) if not looks_like_decline(s) and NUMBER_RE.search(s)]
        if leaked:
            return False, f"declined but still answered: {leaked[0][:100]}"
        return True, "declined an out-of-scope query"
    if declined:
        return False, "declined an in-scope query"
    return True, "answered an in-scope query"


REFUSAL = CodeGrader("refusal", check)
