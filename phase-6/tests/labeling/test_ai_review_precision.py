import builtins
import json

import pytest
from audit_helpers import finding

from evalpilot.audit.flaws import PlantedFlaw, load_planted
from evalpilot.cli import main
from evalpilot.labeling import LabelStore, ai_review_precision
from evalpilot.labeling.audit_inputs import resolve_example_audits
from evalpilot.labeling.calibration import AI_REVIEW_GRADER, ai_item_id, match_flaw
from evalpilot.models import Label

FLAWS = [
    PlantedFlaw(id="F1", title="eval", owasp="LLM10", where="tools.py", required=[["code/llm-output-eval"]]),
    PlantedFlaw(id="F2", title="secret", owasp="LLM02", where="config.py", required=[["regex-secret/"]]),
    PlantedFlaw(id="F3", title="logging", owasp="LLM02", where="bot.py", required=[["code/log-prompt-pii"]]),
]
STATS = {"files_reviewed": 3, "findings_proposed": 5, "rejected": 1, "calls": 3}


def _findings():
    return [
        finding("exec:tools.py", check_id="code/llm-output-eval", location="tools.py:10"),
        finding("secret:config.py", check_id="regex-secret/openai", location="config.py:4", owasp="LLM02"),
        finding("log:bot.py", check_id="code/log-prompt-pii", location="bot.py:84", owasp="LLM02"),
        # corroborated through the merge key
        finding("exec:tools.py", source="ai", check_id="ai-review/LLM10", location="tools.py:8-10"),
        # different key, but fires on the same lines as the secret rule
        finding("ai:config.py:3-5", source="ai", check_id="ai-review/LLM02", location="config.py:3-5", owasp="LLM02"),
        # same file + OWASP as F3 but different lines: not the planted flaw
        finding("ai:bot.py:96-99", source="ai", check_id="ai-review/LLM02", location="bot.py:96-99", owasp="LLM02"),
        finding("ai:server.py:22", source="ai", check_id="ai-review/LLM10", location="server.py:22-23"),
    ]


def test_match_flaw_needs_shared_key_or_overlapping_lines():
    fs = _findings()
    others = [f for f in fs if f.source != "ai"]
    assert [match_flaw(f, FLAWS, others) for f in fs if f.source == "ai"] == ["F1", "F2", None, None]


def test_precision_recall_against_planted_flaws():
    r = ai_review_precision("audit-v", "vulnerable", _findings(), FLAWS, STATS)
    assert (r["kept"], r["matched_planted"], r["unreviewed"]) == (4, 2, 2)
    assert r["precision_planted"] == pytest.approx(0.5)
    assert r["recall_planted"] == pytest.approx(2 / 3)
    assert r["flaws_missed_by_ai"] == ["F3"]
    assert r["rejected_rate"] == pytest.approx(0.2)
    assert r["precision_reviewed"] is None


def test_human_review_settles_unmatched_findings():
    fs = _findings()
    labels = [
        Label(ai_item_id(fs[5]), "audit", AI_REVIEW_GRADER, True, "me", "t", run_id="audit-v"),
        Label(ai_item_id(fs[6]), "audit", AI_REVIEW_GRADER, False, "me", "t", run_id="audit-v"),
        Label(ai_item_id(fs[6]), "audit", AI_REVIEW_GRADER, True, "me", "t", run_id="other-audit"),
    ]
    r = ai_review_precision("audit-v", "vulnerable", fs, FLAWS, STATS, labels)
    assert (r["human_real"], r["human_false_positive"], r["unreviewed"]) == (1, 1, 0)
    assert r["precision_reviewed"] == pytest.approx(3 / 4)


def test_fixed_variant_has_no_planted_matches():
    r = ai_review_precision("audit-f", "fixed", _findings(), FLAWS, STATS)
    assert r["matched_planted"] == 0 and r["precision_planted"] is None and "recall_planted" not in r


def _fake_audit(runs_dir, name, path, findings, stats=STATS):
    d = runs_dir / name
    d.mkdir(parents=True)
    intake = {"audit_id": name, "provider": "offline", "inputs": {"path": path},
              "engine_stats": {"code": {"ai_review": stats}}}
    (d / "intake.json").write_text(json.dumps(intake), encoding="utf-8")
    (d / "risk_register.json").write_text("[]", encoding="utf-8")
    (d / "findings.jsonl").write_text("".join(f.model_dump_json() + "\n" for f in findings), encoding="utf-8")
    return d


def test_resolve_example_audits_picks_latest_per_variant(settings, root):
    fs = _findings()
    _fake_audit(settings.runs_dir, "audit-20260101T000000Z-v", "examples/vulnerable_bot", fs)
    _fake_audit(settings.runs_dir, "audit-20260102T000000Z-v", "examples/vulnerable_bot", fs)
    _fake_audit(settings.runs_dir, "audit-20260102T000000Z-f", "examples/fixed_bot", fs[:2])
    _fake_audit(settings.runs_dir, "audit-20260103T000000Z-x", "examples/fixed_bot", [], stats={"calls": 0})
    audits = resolve_example_audits(settings.runs_dir, root, [])
    assert [(a.audit_id, a.variant) for a in audits] == [
        ("audit-20260102T000000Z-v", "vulnerable"),
        ("audit-20260102T000000Z-f", "fixed"),
    ]
    assert [f.id for f in audits[0].flaws] == [f.id for f in load_planted(root / "examples/vulnerable_bot/PLANTED_FLAWS.json")]


def test_calibrate_cli_reports_ai_review(capsys, root, settings, tmp_path):
    run = settings.runs_dir / "20260101T000000Z-v1"
    run.mkdir(parents=True)
    (run / "grades.jsonl").write_text("", encoding="utf-8")
    _fake_audit(settings.runs_dir, "audit-20260101T000000Z-v", "examples/vulnerable_bot", _findings())
    assert main(["--root", str(root), "calibrate", "--labels", str(tmp_path / "l.jsonl")]) == 1  # no judge labels
    report = json.loads((run / "calibration.json").read_text(encoding="utf-8"))
    [ai] = report["ai_review"]
    assert ai["variant"] == "vulnerable" and ai["kept"] == 4 and ai["proposed"] == 5
    assert "AI review [vulnerable]" in capsys.readouterr().out


def test_label_audit_reviews_only_unmatched_findings(monkeypatch, capsys, root, settings, tmp_path):
    _fake_audit(settings.runs_dir, "audit-20260101T000000Z-v", "examples/vulnerable_bot", _findings())
    labels = tmp_path / "labels.jsonl"
    answers = iter(["p", "f"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert main(["--root", str(root), "label", "--audit", "vulnerable", "--labels", str(labels)]) == 0
    assert "2 AI-review finding(s)" in capsys.readouterr().out  # tools.py and config.py match VB-04 / VB-01
    stored = LabelStore(labels).all()
    assert all(lb.grader == AI_REVIEW_GRADER and lb.run_id == "audit-20260101T000000Z-v" for lb in stored)
    assert sorted(lb.human_pass for lb in stored) == [False, True]

    assert main(["--root", str(root), "label", "--audit", "fixed", "--labels", str(labels)]) == 2
