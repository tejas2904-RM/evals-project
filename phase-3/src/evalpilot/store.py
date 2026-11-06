"""Run ids and JSONL persistence under runs/."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")


def new_run_id(versions: Iterable[str], now: datetime | None = None) -> str:
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{'-'.join(versions)}"


def run_dir(runs_root: Path, run_id: str) -> Path:
    path = runs_root / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_jsonl(path: Path, records: Iterable[Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        for record in records:
            data = record.to_dict() if hasattr(record, "to_dict") else record
            fh.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
            count += 1
    return count


def read_jsonl(path: Path, parse: Callable[[dict[str, Any]], T] | None = None) -> list[T]:
    records: list[Any] = []
    with path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path.name}:{lineno}: invalid JSON ({exc.msg})") from exc
            try:
                records.append(parse(data) if parse else data)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{path.name}:{lineno}: {exc}") from exc
    return records
