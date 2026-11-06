"""Grader protocol and helpers. Every grader answers one yes/no question about one trace."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.models import Case, GradeRecord, Trace

NA = "n/a"

GraderKind = Literal["code", "llm"]
# (passed, evidence), or None when the grader doesn't apply to this case.
CheckResult = tuple[bool, str] | None
CheckFn = Callable[[Case | None, Trace, KnowledgeBase | None], CheckResult | str]


class Grader(Protocol):
    name: str
    kind: GraderKind

    def grade(self, case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> GradeRecord: ...


def is_na(record: GradeRecord) -> bool:
    return record.evidence == NA or record.evidence.startswith(f"{NA}:")


def make_record(trace: Trace, grader: str, kind: GraderKind, passed: bool, evidence: str) -> GradeRecord:
    return GradeRecord(
        run_id=trace.run_id,
        case_id=trace.case_id,
        version=trace.version,
        grader=grader,
        passed=passed,
        evidence=evidence,
        kind=kind,
    )


def not_applicable(reason: str) -> str:
    return f"{NA}: {reason}"


@dataclass(frozen=True)
class CodeGrader:
    """A deterministic grader. `check` returns (passed, evidence) or an `n/a: ...` string."""

    name: str
    check: CheckFn
    kind: GraderKind = "code"

    def grade(self, case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> GradeRecord:
        result = self.check(case, trace, kb)
        if result is None or isinstance(result, str):
            return make_record(trace, self.name, self.kind, True, result or NA)
        passed, evidence = result
        return make_record(trace, self.name, self.kind, bool(passed), evidence)
