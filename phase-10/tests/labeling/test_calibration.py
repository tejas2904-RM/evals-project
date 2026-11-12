import json

import pytest

from evalpilot.cli import main
from evalpilot.config import CalibrationConfig, ConfigError, load_settings
from evalpilot.labeling import Confusion, accuracy, calibrate, cohen_kappa, tnr, tpr
from evalpilot.models import GradeRecord, Label

RUN = "20261106T000000Z-v1-v2-v3"


def grade(case_id, passed, grader="judge_grounded", version="v1", evidence="reason", run_id=RUN):
    return GradeRecord(run_id, case_id, version, grader, passed, evidence, "llm" if grader.startswith("judge") else "code")


def label(case_id, human_pass, grader="judge_grounded", version="v1", run_id=RUN):
    return Label(case_id, version, grader, human_pass, "tester", "2026-11-06T00:00:00Z", run_id=run_id)


def test_kappa_hand_computed():
    # p_o = 30/40 = .75; both raters pass 25/40, so p_e = .625^2 + .375^2 = .53125; kappa = .21875/.46875 = 7/15
    c = Confusion(tp=20, fp=5, tn=10, fn=5)
    assert cohen_kappa(c) == pytest.approx(7 / 15)


def test_kappa_is_one_on_perfect_agreement():
    assert cohen_kappa(Confusion(tp=7, fp=0, tn=3, fn=0)) == pytest.approx(1.0)


def test_kappa_is_zero_when_grader_always_passes():
    c = Confusion.from_pairs([(True, True)] * 6 + [(True, False)] * 4)
    assert cohen_kappa(c) == pytest.approx(0.0)
    assert tpr(c) == 1.0 and tnr(c) == 0.0


def test_kappa_undefined_when_everyone_uses_one_class():
    assert cohen_kappa(Confusion(tp=10)) is None
    assert cohen_kappa(Confusion()) is None


def test_confusion_rates_on_ten_rows():
    pairs = [(True, True)] * 5 + [(True, False)] + [(False, False)] * 3 + [(False, True)]
    c = Confusion.from_pairs(pairs)
    assert (c.tp, c.fp, c.tn, c.fn, c.n) == (5, 1, 3, 1, 10)
    assert tpr(c) == pytest.approx(5 / 6)
    assert tnr(c) == pytest.approx(3 / 4)
    assert accuracy(c) == pytest.approx(0.8)


def test_rates_are_none_without_the_class():
    c = Confusion(tp=3, fn=1)
    assert tnr(c) is None and tpr(c) == 0.75


def test_calibrate_joins_on_run_case_version_grader():
    grades = [grade("a", True), grade("b", False), grade("c", True, evidence="n/a: no context"), grade("d", True)]
    labels = [
        label("a", True),
        label("b", True),               # disagreement: grader fail, human pass
        label("c", False),              # n/a grade -> not scored
        label("d", False, run_id="x"),  # other run judged a different answer -> ignored
        label("z", True),               # no grade -> unmatched
    ]
    report = calibrate(labels, grades, CalibrationConfig(), run_id=RUN)
    g = report["graders"]["judge_grounded"]
    assert g["confusion"] == {"tp": 1, "fp": 0, "tn": 0, "fn": 1}
    assert g["unmatched_labels"] == 2
    assert [d["case_id"] for d in g["disagreements"]] == ["b"]
    assert not report["enough_labels"]


def _balanced(grader, n):
    """n labels: grader and human agree on all but one pass and one fail."""
    grades, labels = [], []
    for i in range(n):
        passed = i % 2 == 0
        grades.append(grade(f"{grader}{i}", passed, grader))
        labels.append(label(f"{grader}{i}", passed if i not in (0, 1) else not passed, grader))
    return grades, labels


def test_calibrate_targets_and_minimums():
    cfg = CalibrationConfig(min_labels=60, min_per_judge=30)
    g1, l1 = _balanced("judge_grounded", 30)
    g2, l2 = _balanced("judge_helpful_compliant", 30)
    report = calibrate(l1 + l2, g1 + g2, cfg, run_id=RUN)
    assert report["enough_labels"] and report["judge_labels"] == 60
    j = report["graders"]["judge_grounded"]
    assert j["tpr"] == pytest.approx(14 / 15) and j["tnr"] == pytest.approx(14 / 15)
    assert j["meets_targets"]

    report = calibrate(l1 + l2[:29], g1 + g2, cfg, run_id=RUN)
    assert not report["enough_labels"]
    assert any("judge_helpful_compliant: 29 labels < 30" in p for p in report["problems"])


def test_code_grader_labels_are_a_sanity_check(settings):
    grades = [grade(f"r{i}", True, "refusal") for i in range(10)]
    labels = [label(f"r{i}", True, "refusal") for i in range(10)]
    report = calibrate(labels, grades, settings.calibration, run_id=RUN)
    r = report["graders"]["refusal"]
    assert r["kind"] == "code" and r["enough_labels"] and r["kappa"] is None
    assert "refusal" not in " ".join(report["problems"])


def _write_run(settings, grades, labels, tmp_path):
    run = settings.runs_dir / RUN
    run.mkdir(parents=True)
    (run / "grades.jsonl").write_text("".join(json.dumps(g.to_dict()) + "\n" for g in grades), encoding="utf-8")
    labels_path = tmp_path / "labels.jsonl"
    labels_path.write_text("".join(json.dumps(lb.to_dict()) + "\n" for lb in labels), encoding="utf-8")
    return run, labels_path


def test_calibrate_cli_exit_codes(capsys, root, settings, tmp_path):
    g1, l1 = _balanced("judge_grounded", 30)
    g2, l2 = _balanced("judge_helpful_compliant", 30)
    run, labels_path = _write_run(settings, g1 + g2, l1 + l2, tmp_path)
    base = ["--root", str(root), "calibrate", "--run", RUN, "--labels", str(labels_path), "--audits", ""]

    assert main(base + ["--min-labels", "60"]) == 0
    out = capsys.readouterr().out
    assert "judge_grounded" in out and "ok" in out
    report = json.loads((run / "calibration.json").read_text(encoding="utf-8"))
    assert report["enough_labels"] and report["graders"]["judge_grounded"]["kappa"] == pytest.approx(13 / 15)

    assert main(base + ["--min-labels", "61"]) == 1
    assert "judge labels in total: 60 < 61" in capsys.readouterr().err
    assert json.loads((run / "calibration.json").read_text(encoding="utf-8"))["enough_labels"] is False


def test_calibrate_cli_without_grades_is_usage_error(capsys, root):
    assert main(["--root", str(root), "calibrate"]) == 2
    assert "no grades found" in capsys.readouterr().err


def test_calibration_config_rejects_unknown_keys(tmp_project):
    cfg = tmp_project / "evals.toml"
    cfg.write_text(cfg.read_text(encoding="utf-8") + "\n[calibration.extra]\nfoo = 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="calibration"):
        load_settings(tmp_project)


def test_calibration_config_defaults(settings):
    c = settings.calibration
    assert (c.min_labels, c.min_per_judge, c.min_per_code_grader) == (60, 30, 10)
    assert (c.target_tpr, c.target_tnr, c.target_kappa) == (0.85, 0.85, 0.60)
