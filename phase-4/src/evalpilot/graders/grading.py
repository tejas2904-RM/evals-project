"""Grade stored traces (never re-run the bot) and summarise pass rates."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import Grader, is_na
from evalpilot.models import Case, GradeRecord, Trace
from evalpilot.store import read_jsonl, write_jsonl

TRACES_FILE = "traces.jsonl"
GRADES_FILE = "grades.jsonl"


@dataclass(frozen=True)
class PassRate:
    passed: int = 0
    applicable: int = 0
    na: int = 0

    @property
    def rate(self) -> float | None:
        return self.passed / self.applicable if self.applicable else None

    def add(self, record: GradeRecord) -> PassRate:
        if is_na(record):
            return PassRate(self.passed, self.applicable, self.na + 1)
        return PassRate(self.passed + record.passed, self.applicable + 1, self.na)


def grade_traces(
    traces: Iterable[Trace],
    cases: dict[str, Case],
    kb: KnowledgeBase | None,
    graders: list[Grader],
    on_record: Callable[[GradeRecord], None] | None = None,
) -> list[GradeRecord]:
    records: list[GradeRecord] = []
    for trace in traces:
        case = cases.get(trace.case_id)
        for grader in graders:
            record = grader.grade(case, trace, kb)
            if not isinstance(record.passed, bool):
                raise TypeError(f"{grader.name} returned a non-binary result")
            records.append(record)
            if on_record:
                on_record(record)
    return records


def summarize(records: Iterable[GradeRecord]) -> dict[str, dict[str, PassRate]]:
    """{grader: {version: PassRate}}; n/a excluded from denominators."""
    table: dict[str, dict[str, PassRate]] = {}
    for record in records:
        row = table.setdefault(record.grader, {})
        row[record.version] = row.get(record.version, PassRate()).add(record)
    return table


def latest_run(runs_dir: Path) -> Path | None:
    candidates = [p for p in runs_dir.glob("*") if (p / TRACES_FILE).is_file() and not p.name.startswith("audit-")]
    return max(candidates, key=lambda p: p.name) if candidates else None


def load_traces(run_path: Path) -> list[Trace]:
    return read_jsonl(run_path / TRACES_FILE, Trace.from_dict)


def write_grades(run_path: Path, records: list[GradeRecord]) -> Path:
    path = run_path / GRADES_FILE
    write_jsonl(path, records)
    return path
