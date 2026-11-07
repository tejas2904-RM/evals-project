"""Per case x grader: fixed | regressed | still_pass | still_fail between a baseline and a candidate."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from evalpilot.graders.base import is_na
from evalpilot.models import GradeRecord

OUTCOMES = ("fixed", "regressed", "still_pass", "still_fail")


@dataclass
class GraderDiff:
    grader: str
    fixed: list[str] = field(default_factory=list)
    regressed: list[str] = field(default_factory=list)
    still_pass: list[str] = field(default_factory=list)
    still_fail: list[str] = field(default_factory=list)
    # n/a on either side, or the case is missing from one side
    not_comparable: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {o: len(getattr(self, o)) for o in (*OUTCOMES, "not_comparable")}

    def to_dict(self) -> dict[str, Any]:
        return {"grader": self.grader, "counts": self.counts(),
                **{o: getattr(self, o) for o in (*OUTCOMES, "not_comparable")}}


@dataclass
class Comparison:
    baseline: str
    candidate: str
    graders: dict[str, GraderDiff]

    def to_dict(self) -> dict[str, Any]:
        return {"baseline": self.baseline, "candidate": self.candidate,
                "graders": {name: d.to_dict() for name, d in self.graders.items()}}


def for_version(records: Iterable[GradeRecord], version: str) -> list[GradeRecord]:
    return [r for r in records if r.version == version]


def classify(baseline: GradeRecord | None, candidate: GradeRecord | None) -> str:
    if baseline is None or candidate is None or is_na(baseline) or is_na(candidate):
        return "not_comparable"
    if baseline.passed:
        return "still_pass" if candidate.passed else "regressed"
    return "fixed" if candidate.passed else "still_fail"


def diff_grades(
    baseline: Iterable[GradeRecord], candidate: Iterable[GradeRecord], *, baseline_label: str, candidate_label: str
) -> Comparison:
    """Both inputs hold one version each; records are matched on (case_id, grader)."""
    base = {(r.case_id, r.grader): r for r in baseline}
    cand = {(r.case_id, r.grader): r for r in candidate}
    graders: dict[str, GraderDiff] = {}
    for case_id, grader in sorted(base.keys() | cand.keys()):
        outcome = classify(base.get((case_id, grader)), cand.get((case_id, grader)))
        getattr(graders.setdefault(grader, GraderDiff(grader)), outcome).append(case_id)
    return Comparison(baseline_label, candidate_label, graders)
