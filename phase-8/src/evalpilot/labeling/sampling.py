"""Stratified sampling of grade records to label: version x category x grader outcome."""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from evalpilot.graders.base import is_na
from evalpilot.models import Case, GradeRecord, Trace


@dataclass(frozen=True)
class LabelItem:
    case: Case
    trace: Trace
    grade: GradeRecord

    @property
    def stratum(self) -> tuple[str, str, bool]:
        return (self.grade.version, self.case.category, self.grade.passed)


def build_items(
    grades: Iterable[GradeRecord], traces: Iterable[Trace], cases: dict[str, Case], grader: str
) -> list[LabelItem]:
    """Labelable items for one grader; n/a records are skipped (there is nothing to agree with)."""
    by_key = {(t.case_id, t.version): t for t in traces}
    items = []
    for g in grades:
        if g.grader != grader or is_na(g):
            continue
        trace, case = by_key.get((g.case_id, g.version)), cases.get(g.case_id)
        if trace is not None and case is not None:
            items.append(LabelItem(case, trace, g))
    return items


def stratified_sample(
    items: Iterable[LabelItem], n: int, *, seed: int = 0, exclude: set[tuple[str, str]] = frozenset()
) -> list[LabelItem]:
    """Round-robin across strata so rare cells (e.g. judge fails on v3) are not drowned out.

    `exclude` holds (case_id, version) pairs already labelled, which makes the CLI resumable.
    """
    strata: dict[tuple[str, str, bool], list[LabelItem]] = defaultdict(list)
    for item in items:
        if (item.case.id, item.grade.version) not in exclude:
            strata[item.stratum].append(item)
    rng = random.Random(seed)
    queues = []
    for key in sorted(strata):
        bucket = sorted(strata[key], key=lambda it: it.case.id)
        rng.shuffle(bucket)
        queues.append(bucket)
    picked: list[LabelItem] = []
    while len(picked) < n and any(queues):
        for queue in queues:
            if queue and len(picked) < n:
                picked.append(queue.pop())
    return picked


def strata_counts(items: Iterable[LabelItem]) -> dict[tuple[str, str, bool], int]:
    counts: dict[tuple[str, str, bool], int] = defaultdict(int)
    for item in items:
        counts[item.stratum] += 1
    return dict(counts)
