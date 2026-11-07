"""Run selected cases x versions and persist traces under runs/<run_id>/."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from evalpilot.bot.bot import run_case
from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.bot.retriever import retriever_for
from evalpilot.config import Settings
from evalpilot.llm import LlmClient
from evalpilot.models import Case, Doc, Trace
from evalpilot.store import new_run_id, run_dir


@dataclass
class RunResult:
    run_id: str
    path: Path
    traces: list[Trace] = field(default_factory=list)
    complete: bool = False

    def by_version(self, version: str) -> list[Trace]:
        return [t for t in self.traces if t.version == version]


def execute_run(
    settings: Settings,
    client: LlmClient,
    cases: list[Case],
    docs: list[Doc],
    versions: list[str],
    *,
    run_id: str | None = None,
    on_trace: Callable[[Trace], None] | None = None,
) -> RunResult:
    run_id = run_id or new_run_id(versions)
    out = run_dir(settings.runs_dir, run_id)
    kb = KnowledgeBase(docs)
    result = RunResult(run_id=run_id, path=out)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        with (out / "traces.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
            for version in versions:
                retriever = retriever_for(version, kb, settings.top_k)
                for case in cases:
                    trace = run_case(case, version, client, kb, retriever, run_id)
                    fh.write(json.dumps(trace.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
                    fh.flush()
                    result.traces.append(trace)
                    if on_trace:
                        on_trace(trace)
        result.complete = True
    finally:
        meta = {
            "run_id": run_id,
            "provider": client.provider.name,
            "bot_model": settings.bot_model,
            "versions": versions,
            "case_ids": [c.id for c in cases],
            "started": started,
            "finished": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "complete": result.complete,
            "n_traces": len(result.traces),
            "cost_usd": round(sum(t.cost_usd for t in result.traces), 6),
            "cache_hits": sum(t.cached for t in result.traces),
        }
        (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return result
