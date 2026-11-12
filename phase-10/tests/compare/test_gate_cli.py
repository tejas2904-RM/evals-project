import json

import pytest

from evalpilot.cli import main
from evalpilot.compare import default_baseline, evaluate_gate
from evalpilot.config import load_settings
from evalpilot.graders.grading import latest_graded_run, load_grades

REFERENCE_RUN = "20261106T143944Z-v1-v2-v3"


@pytest.fixture(scope="module")
def offline_run(tmp_path_factory):
    """One offline run + grade shared by the CLI tests (the autouse env fixture isn't module-scoped)."""
    mp = pytest.MonkeyPatch()
    tmp = tmp_path_factory.mktemp("gate")
    for var in ("OPENAI_API_KEY", "EVALPILOT_ROOT"):
        mp.delenv(var, raising=False)
    mp.setattr("evalpilot.config.load_dotenv", lambda _path: None)
    mp.setenv("EVALPILOT_BOT_MODEL", "gpt-5.4-nano")
    mp.setenv("EVALPILOT_JUDGE_MODEL", "gpt-5.4-mini")
    mp.setenv("EVALPILOT_CACHE_DIR", str(tmp / ".cache"))
    mp.setenv("EVALPILOT_RUNS_DIR", str(tmp / "runs"))
    from conftest import PROJECT_ROOT

    assert main(["--root", str(PROJECT_ROOT), "run", "--provider", "offline"]) == 0
    assert main(["--root", str(PROJECT_ROOT), "grade", "--provider", "offline"]) == 0
    mp.undo()
    return tmp / "runs"


@pytest.fixture
def runs(offline_run, monkeypatch):
    monkeypatch.setenv("EVALPILOT_RUNS_DIR", str(offline_run))
    return offline_run


def test_gate_v1_blocked_with_reasons(capsys, root, runs):
    assert main(["--root", str(root), "gate", "--version", "v1"]) == 1
    out = capsys.readouterr().out
    assert "BLOCKED" in out and "grader | rule | threshold | observed | case_ids" in out
    assert "citation | min_pass_rate | >= 85% | 0/28 (0%) | cit_01" in out
    run = latest_graded_run(runs)
    report = json.loads((run / "gate_v1.json").read_text(encoding="utf-8"))
    assert report["verdict"] == "BLOCKED" and report["baseline"] is None
    assert {v["grader"] for v in report["violations"]} >= {"refusal", "advice", "unsafe_claim", "citation"}


def test_gate_v3_passes(capsys, root, runs):
    assert main(["--root", str(root), "gate", "--version", "v3"]) == 0
    out = capsys.readouterr().out
    assert "Gate v3 (baseline v2)" in out and ": PASS" in out


def test_gate_v2_vs_v1_improves_but_blocks_on_entities(capsys, root, runs):
    assert main(["--root", str(root), "gate", "--version", "v2"]) == 1
    out = capsys.readouterr().out
    assert "wrong_entity | min_pass_rate" in out and "improvement_over_v1" not in out


def test_gate_baseline_none_skips_regressions(capsys, root, runs):
    assert main(["--root", str(root), "gate", "--version", "v3", "--baseline", "none"]) == 0
    assert "baseline none" in capsys.readouterr().out


def test_gate_usage_errors(capsys, root, runs):
    assert main(["--root", str(root), "gate", "--version", "v9"]) == 2
    assert main(["--root", str(root), "gate", "--version", "v2", "--baseline", "v2"]) == 2
    assert main(["--root", str(root), "gate", "--version", "v1", "--run", "nope"]) == 2
    assert "no grades found" in capsys.readouterr().err


def test_gate_without_runs_is_usage_error(capsys, root):
    assert main(["--root", str(root), "gate", "--version", "v1"]) == 2


def test_compare_writes_case_ids(capsys, root, runs):
    assert main(["--root", str(root), "compare", "--baseline", "v1", "--candidate", "v2"]) == 0
    out = capsys.readouterr().out
    assert "fixed     :" in out and "oos_01" in out
    data = json.loads((latest_graded_run(runs) / "compare_v1_v2.json").read_text(encoding="utf-8"))
    assert "oos_01" in data["graders"]["refusal"]["fixed"]
    assert data["graders"]["refusal"]["regressed"] == []
    assert sum(data["graders"]["citation"]["counts"].values()) == 41


def test_compare_v2_v3_has_no_regressions(root, runs):
    assert main(["--root", str(root), "compare", "--baseline", "v2", "--candidate", "v3"]) == 0
    data = json.loads((latest_graded_run(runs) / "compare_v2_v3.json").read_text(encoding="utf-8"))
    assert all(not d["regressed"] for d in data["graders"].values())
    assert data["graders"]["wrong_entity"]["fixed"] == ["ent_01", "ent_02", "ent_03", "ent_04", "ent_05"]


def test_compare_across_runs(root, runs):
    latest = latest_graded_run(runs)
    older = runs / "20000101T000000Z-v1-v2-v3"
    if not older.exists():
        older.mkdir()
        (older / "grades.jsonl").write_bytes((latest / "grades.jsonl").read_bytes())
    assert main(["--root", str(root), "compare", "--baseline", "v3", "--candidate", "v3",
                 "--baseline-run", older.name]) == 0
    data = json.loads((latest / f"compare_{older.name}.v3_v3.json").read_text(encoding="utf-8"))
    assert data["baseline"] == f"{older.name}:v3"
    assert all(not d["regressed"] and not d["fixed"] for d in data["graders"].values())


def test_compare_rejects_unknown_version(root, runs):
    assert main(["--root", str(root), "compare", "--baseline", "v0", "--candidate", "v2"]) == 2


def test_reference_run_is_ignored_by_latest(tmp_path):
    (tmp_path / "reference").mkdir()
    (tmp_path / "reference" / "grades.jsonl").write_text("", encoding="utf-8")
    assert latest_graded_run(tmp_path) is None


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_committed_reference_gate_reproduces(root, version, monkeypatch):
    """The paid run in runs/reference/ gates exactly as its committed gate_<v>.json, with no key."""
    monkeypatch.delenv("EVALPILOT_RUNS_DIR")
    settings = load_settings(root)
    run = settings.runs_dir / "reference" / REFERENCE_RUN
    recorded = json.loads((run / f"gate_{version}.json").read_text(encoding="utf-8"))
    result = evaluate_gate(load_grades(run), version, settings.gate, baseline=default_baseline(version))
    assert result.verdict == recorded["verdict"]
    assert [v.line() for v in result.violations] == [
        f"{v['grader']} | {v['rule']} | {v['threshold']} | {v['observed']} | {', '.join(v['case_ids']) or '-'}"
        for v in recorded["violations"]
    ]
