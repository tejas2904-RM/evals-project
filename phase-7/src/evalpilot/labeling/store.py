"""Human labels in data/labels.jsonl, one row per (run, case, version, grader)."""

from __future__ import annotations

import os
from pathlib import Path

from evalpilot.models import Label
from evalpilot.store import read_jsonl, write_jsonl


class LabelStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._labels: dict[tuple[str, str, str, str], Label] = {}
        if path.is_file():
            for label in read_jsonl(path, Label.from_dict):
                self._labels[label.key] = label

    def __len__(self) -> int:
        return len(self._labels)

    def all(self) -> list[Label]:
        return sorted(self._labels.values(), key=lambda lb: lb.key)

    def for_run(self, run_id: str, grader: str | None = None) -> list[Label]:
        return [lb for lb in self.all() if lb.run_id == run_id and (grader is None or lb.grader == grader)]

    def get(self, run_id: str, case_id: str, version: str, grader: str) -> Label | None:
        return self._labels.get((run_id, case_id, version, grader))

    def upsert(self, label: Label) -> bool:
        """Insert or replace; returns True when it replaced an earlier label. Saved immediately."""
        replaced = label.key in self._labels
        self._labels[label.key] = label
        self._save()
        return replaced

    def _save(self) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        write_jsonl(tmp, self.all())
        os.replace(tmp, self.path)
