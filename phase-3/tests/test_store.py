from datetime import datetime, timezone

from evalpilot.models import Trace
from evalpilot.store import new_run_id, read_jsonl, run_dir, write_jsonl


def test_run_id_format():
    now = datetime(2026, 11, 6, 8, 30, tzinfo=timezone.utc)
    assert new_run_id(["v1", "v3"], now) == "20261106T083000Z-v1-v3"


def test_jsonl_round_trip(tmp_path):
    trace = Trace(
        run_id="r", case_id="c", version="v2", query="q", retrieved_doc_ids=["d"],
        answer="a [d]", citations=["d"], refused=False, model="m", provider="offline",
    )
    path = run_dir(tmp_path, "r") / "traces.jsonl"
    assert write_jsonl(path, [trace, trace]) == 2
    assert read_jsonl(path, Trace.from_dict) == [trace, trace]
