import json

from evalpilot.cli import main
from evalpilot.graders import summarize
from evalpilot.models import GradeRecord


def _rates(run_dir):
    records = [GradeRecord.from_dict(json.loads(line)) for line in (run_dir / "grades.jsonl").open(encoding="utf-8")]
    return records, summarize(records)


def test_grade_offline_writes_984_records_with_expected_ordering(capsys, root, settings):
    assert main(["--root", str(root), "run", "--provider", "offline"]) == 0
    assert main(["--root", str(root), "grade", "--provider", "offline"]) == 0
    out = capsys.readouterr().out
    assert "984 grade records" in out and "Spend: $0.0000" in out
    [run] = [p for p in settings.runs_dir.iterdir() if p.is_dir()]
    records, table = _rates(run)
    assert len(records) == 123 * 8
    assert all(isinstance(r.passed, bool) for r in records)
    for grader in ("refusal", "advice", "unsafe_claim", "citation"):
        assert table[grader]["v2"].rate > table[grader]["v1"].rate, grader
    assert table["wrong_entity"]["v3"].rate > table["wrong_entity"]["v2"].rate
    assert not any(r.evidence.startswith("judge_parse_error") for r in records)


def test_grade_code_only(capsys, root, settings):
    assert main(["--root", str(root), "run", "--provider", "offline", "--version", "v3"]) == 0
    assert main(["--root", str(root), "grade", "--graders", "code"]) == 0
    assert "246 grade records" in capsys.readouterr().out


def test_grade_without_runs_is_usage_error(capsys, root):
    assert main(["--root", str(root), "grade"]) == 2
    assert "no traces found" in capsys.readouterr().err


def test_grade_bad_selection(root):
    assert main(["--root", str(root), "grade", "--graders", "some"]) == 2
