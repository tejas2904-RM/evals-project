import builtins
import json

from evalpilot.cli import main
from evalpilot.labeling import LabelStore, build_items, stratified_sample
from evalpilot.labeling.label_cli import render, run_session, trace_label
from evalpilot.labeling.sampling import LabelItem
from evalpilot.models import GradeRecord, Label, Trace


def _label(case_id="c1", human_pass=True, run_id="r1", **kw):
    return Label(case_id, kw.get("version", "v1"), kw.get("grader", "judge_grounded"), human_pass, "me",
                 "2026-11-06T00:00:00Z", run_id=run_id)


def test_upsert_replaces_and_persists(tmp_path):
    path = tmp_path / "labels.jsonl"
    store = LabelStore(path)
    assert store.upsert(_label()) is False
    assert store.upsert(_label(case_id="c2")) is False
    assert store.upsert(_label(human_pass=False)) is True
    reloaded = LabelStore(path)
    assert len(reloaded) == 2
    assert reloaded.get("r1", "c1", "v1", "judge_grounded").human_pass is False
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_same_case_in_another_run_is_a_separate_label(tmp_path):
    store = LabelStore(tmp_path / "labels.jsonl")
    store.upsert(_label(run_id="r1"))
    store.upsert(_label(run_id="r2", human_pass=False))
    assert len(store) == 2 and len(store.for_run("r1")) == 1


def test_old_labels_without_run_id_still_load(tmp_path):
    path = tmp_path / "labels.jsonl"
    row = {"case_id": "c1", "version": "v1", "grader": "judge_grounded", "human_pass": True, "labeler": "me", "ts": "t"}
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert LabelStore(path).all()[0].run_id == ""


def _items(cases_by_id, n_per_version=6):
    items = []
    for version in ("v1", "v2", "v3"):
        for i, case in enumerate(list(cases_by_id.values())[:n_per_version]):
            trace = Trace("r1", case.id, version, case.query, [], f"answer {case.id}", [], False, "m", "offline")
            items.append(LabelItem(case, trace, GradeRecord("r1", case.id, version, "judge_grounded", i % 3 != 0, "why", "llm")))
    return items


def test_stratified_sample_covers_every_stratum_first(cases_by_id):
    items = _items(cases_by_id)
    strata = {it.stratum for it in items}
    picked = stratified_sample(items, len(strata), seed=1)
    assert {it.stratum for it in picked} == strata
    assert stratified_sample(items, 5, seed=1) == stratified_sample(items, 5, seed=1)


def test_stratified_sample_excludes_labelled_and_na(cases_by_id):
    items = _items(cases_by_id)
    done = {(items[0].case.id, "v1")}
    picked = stratified_sample(items, 100, exclude=done)
    assert len(picked) == len(items) - 1
    na = GradeRecord("r1", "x", "v1", "judge_grounded", True, "n/a: no context", "llm")
    assert build_items([na], [], cases_by_id, "judge_grounded") == []


def test_session_keys_and_quit(tmp_path, cases_by_id):
    store = LabelStore(tmp_path / "labels.jsonl")
    answers = iter(["p", "maybe", "f", "s", "q"])
    shown = []
    result = run_session(_items(cases_by_id)[:6], store, labeler="me", ask=lambda _p: next(answers), say=shown.append,
                         show=lambda it, i, n: f"{i}/{n} {it.case.id}", to_label=trace_label)
    assert (result.labelled, result.skipped, result.quit) == (2, 1, True)
    assert [lb.human_pass for lb in store.all()] in ([True, False], [False, True])
    assert "  please type p, f, s or q" in shown


def test_session_treats_eof_as_quit(tmp_path, cases_by_id):
    def eof(_prompt):
        raise EOFError

    result = run_session(_items(cases_by_id)[:2], LabelStore(tmp_path / "l.jsonl"), labeler="me", ask=eof,
                         say=lambda _s: None, show=lambda *_: "", to_label=trace_label)
    assert result.quit and result.labelled == 0


def test_render_shows_query_context_answer_and_verdict(cases_by_id, kb):
    item = _items(cases_by_id)[0]
    text = render(item, kb, index=1, total=1, blind=False)
    assert item.case.query[:30] in text and "RETRIEVED CONTEXT" in text and "GRADER VERDICT: FAIL" in text
    assert "hidden (--blind)" in render(item, kb, index=1, total=1, blind=True)


def test_label_cli_resumes(monkeypatch, capsys, root, tmp_path):
    assert main(["--root", str(root), "run", "--provider", "offline", "--version", "v1"]) == 0
    assert main(["--root", str(root), "grade", "--provider", "offline"]) == 0
    labels = tmp_path / "labels.jsonl"
    cmd = ["--root", str(root), "label", "--grader", "judge_grounded", "--n", "4", "--labels", str(labels)]

    answers = iter(["p", "f", "q"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert main(cmd) == 0
    first = LabelStore(labels).all()
    assert len(first) == 2
    capsys.readouterr()

    answers = iter(["p", "p", "p", "p"])
    monkeypatch.setattr(builtins, "input", lambda _p="": next(answers))
    assert main(cmd) == 0
    out = capsys.readouterr().out
    assert "2 labelled" in out and "judge_grounded: 6 label(s)" in out
    keys = [lb.key for lb in LabelStore(labels).all()]
    assert len(keys) == len(set(keys)) == 6
    assert {lb.key for lb in first} <= set(keys)


def test_label_cli_rejects_unknown_grader(root, tmp_path):
    assert main(["--root", str(root), "label", "--grader", "nope", "--labels", str(tmp_path / "l.jsonl")]) == 2
