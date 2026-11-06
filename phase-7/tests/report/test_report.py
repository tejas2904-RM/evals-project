import json
import re
import shutil

import pytest

from evalpilot.cli import main
from evalpilot.config import load_settings
from evalpilot.graders.grading import load_grades
from evalpilot.labeling import LabelStore
from evalpilot.llm import Ledger
from evalpilot.models import Label
from evalpilot.report import Sources, audit_dirs, build_context, render_html, select_audits

REFERENCE_RUN = "20261106T143944Z-v1-v2-v3"
XSS = '<script>alert(1)</script><img src=x onerror=alert(2)>'


@pytest.fixture
def ref_runs(root, tmp_path, monkeypatch):
    """A private copy of runs/reference/ so CLI writes never touch the committed artefacts."""
    runs = tmp_path / "runs"
    shutil.copytree(root / "runs" / "reference", runs / "reference")
    monkeypatch.setenv("EVALPILOT_RUNS_DIR", str(runs))
    return runs


def sources(runs, labels_path, version="v3"):
    ref = runs / "reference"
    run = ref / REFERENCE_RUN
    return Sources(run, select_audits(audit_dirs(ref / "audits"), run, version), ref / "spend.jsonl", labels_path, version)


@pytest.fixture
def ctx(ref_runs, root, tmp_path):
    return build_context(load_settings(root), sources(ref_runs, tmp_path / "labels.jsonl"))


def html_for(ctx, root):
    return render_html(ctx, load_settings(root).gate.min_pass_rate)


def test_builds_from_reference_offline(ctx):
    assert ctx["versions"] == ["v1", "v2", "v3"] and len(ctx["cases"]) == 41
    assert {v: g["verdict"] for v, g in ctx["gates"].items()} == {"v1": "BLOCKED", "v2": "BLOCKED", "v3": "BLOCKED"}
    assert sorted(a["role"] for a in ctx["audits"]) == ["bot", "fixed", "vulnerable"]
    assert ctx["final"]["decision"] == "BLOCK" and ctx["final"]["audit_id"]


def test_final_verdict_names_gate_rule_and_audit_risk(ctx):
    final = ctx["final"]
    assert final["deciding_rules"] == ["judge_grounded | regressions_vs_v2 | <= 0 | 1 | adv_05"]
    assert final["deciding_risks"] and final["gate_verdict"] == "BLOCKED"


def test_report_is_one_file_with_no_remote_assets(ctx, root):
    html = html_for(ctx, root)
    assert html.startswith("<!doctype html>") and html.count("<script>") == 1 and html.count("<style>") == 1
    assert not re.search(r"<(?:script|link|img|iframe|object|embed)\b[^>]*\b(?:src|href)=", html, re.I)
    assert not re.search(r"@import|url\(\s*['\"]?(?:https?:)?//", html, re.I)


def test_report_contains_gate_audit_verdicts_spend_and_kappa(ctx, root, ref_runs):
    html = html_for(ctx, root)
    total = sum(e.cost_usd for e in Ledger(ref_runs / "reference" / "spend.jsonl").entries())
    assert "Final verdict for v3: BLOCK" in html
    assert '<span class="badge BLOCKED">BLOCKED</span>' in html
    assert '<span class="badge SHIP">SHIP</span>' in html and '<span class="badge BLOCK">BLOCK</span>' in html
    assert f"${total:.4f}" in html and "$3.00 budget guard" in html
    assert "&kappa;" in html
    for heading in ("Release gate", "Pass rates", "Compare", "Judge calibration", "Case explorer", "Audit", "Risk register",
                    "Guardrail coverage map", "Evidence drill-down", "Definition of done"):
        assert heading in html, heading


def test_kappa_value_appears_once_labels_exist(ref_runs, root, tmp_path):
    settings = load_settings(root)
    run = ref_runs / "reference" / REFERENCE_RUN
    store = LabelStore(tmp_path / "labels.jsonl")
    grades = [g for g in load_grades(run) if g.grader == "judge_grounded"]
    for g in grades[:40]:
        store.upsert(Label(case_id=g.case_id, version=g.version, grader="judge_grounded", human_pass=g.passed,
                           labeler="t", ts="2026-11-06T00:00:00+00:00", run_id=REFERENCE_RUN))
    ctx = build_context(settings, sources(ref_runs, tmp_path / "labels.jsonl"))
    g = ctx["calibration"]["graders"]["judge_grounded"]
    assert g["n_labels"] == 40 and g["kappa"] is not None
    assert f"{g['kappa']:.2f}" in html_for(ctx, root)


def test_bot_answers_are_escaped(ctx, root):
    ctx["cases"][0]["versions"]["v1"]["answer"] = XSS
    ctx["audits"][0]["risks"][0]["title"] = XSS
    html = html_for(ctx, root)
    assert XSS not in html and "onerror=alert(2)&gt;" in html
    assert html.count("<script>") == 1 and "<img" not in html


def test_report_is_deterministic(ctx, root):
    assert html_for(ctx, root) == html_for(ctx, root)


def test_committed_docs_report_is_current(ctx, root):
    """docs/report.html must be regenerated (`evalpilot report --reference`) whenever its inputs change."""
    assert (root / "docs" / "report.html").read_text(encoding="utf-8") == html_for(ctx, root)


def test_dod_rows(ctx):
    rows = {d["item"]: d["status"] for d in ctx["dod"]}
    assert rows["v2 beats v1 on refusal, advice, unsafe_claim and citation"] == "pass"
    assert rows["Every planted flaw found in vulnerable_bot (BLOCK) and closed in fixed_bot (SHIP)"] == "pass"
    assert rows["Audit exported as Markdown and PDF"] == "pass"
    assert rows["Total OpenAI spend under $5"] == "pass"
    assert rows["v1 fails the gate; v3 passes, or the report says exactly why"] == "explained"


def test_unknown_version_is_an_error(ref_runs, root, tmp_path):
    with pytest.raises(ValueError, match="v9"):
        build_context(load_settings(root), sources(ref_runs, tmp_path / "labels.jsonl", version="v9"))


def test_report_cli_from_reference(ref_runs, root, tmp_path, capsys):
    out = tmp_path / "site" / "report.html"
    assert main(["--root", str(root), "report", "--reference", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "final verdict v3: BLOCK" in printed and "audit (bot): BLOCK" in printed
    assert out.read_text(encoding="utf-8").startswith("<!doctype html>")


def test_verdict_cli_writes_json_and_exits_1(ref_runs, root, capsys):
    assert main(["--root", str(root), "verdict", "--version", "v3", "--run", f"reference/{REFERENCE_RUN}"]) == 1
    out = capsys.readouterr().out
    assert "Final verdict v3: BLOCK" in out and "adv_05" in out
    payload = json.loads((ref_runs / "reference" / REFERENCE_RUN / "verdict_v3.json").read_text(encoding="utf-8"))
    assert payload["decision"] == "BLOCK" and payload["deciding_risks"]
    audit = ref_runs / "reference" / "audits" / payload["audit_id"]
    assert json.loads((audit / "final_verdict.json").read_text(encoding="utf-8")) == payload


def test_verdict_without_matching_audit_blocks(ref_runs, root, capsys):
    shutil.rmtree(ref_runs / "reference" / "audits")
    assert main(["--root", str(root), "verdict", "--version", "v3", "--run", f"reference/{REFERENCE_RUN}"]) == 1
    assert "no audit of this version" in capsys.readouterr().out
