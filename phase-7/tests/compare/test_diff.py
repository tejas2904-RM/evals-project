from evalpilot.compare import OUTCOMES, diff_grades, for_version
from evalpilot.compare.diff import classify
from evalpilot.models import GradeRecord


def g(case_id, passed, version="v1", grader="refusal", evidence="e"):
    return GradeRecord("r", case_id, version, grader, passed, evidence, "code")


def test_classify_truth_table():
    assert classify(g("a", False), g("a", True)) == "fixed"
    assert classify(g("a", True), g("a", False)) == "regressed"
    assert classify(g("a", True), g("a", True)) == "still_pass"
    assert classify(g("a", False), g("a", False)) == "still_fail"


def test_na_or_missing_is_not_comparable():
    na = g("a", True, evidence="n/a: refused")
    assert classify(na, g("a", False)) == "not_comparable"
    assert classify(g("a", False), na) == "not_comparable"
    assert classify(None, g("a", True)) == "not_comparable"


def test_diff_lists_case_ids_per_outcome():
    base = [g("fix", False), g("reg", True), g("sp", True), g("sf", False), g("na", True, evidence="n/a")]
    cand = [g(c.case_id, p, "v2", evidence=c.evidence) for c, p in zip(base, [True, False, True, False, False])]
    result = diff_grades(base, cand, baseline_label="v1", candidate_label="v2")
    d = result.graders["refusal"]
    assert (d.fixed, d.regressed, d.still_pass, d.still_fail, d.not_comparable) == (["fix"], ["reg"], ["sp"], ["sf"], ["na"])
    assert d.counts() == {o: 1 for o in (*OUTCOMES, "not_comparable")}
    assert result.to_dict()["graders"]["refusal"]["regressed"] == ["reg"]


def test_diff_keeps_graders_apart():
    base = [g("a", True), g("a", False, grader="advice")]
    cand = [g("a", False, "v2"), g("a", True, "v2", grader="advice")]
    result = diff_grades(base, cand, baseline_label="v1", candidate_label="v2")
    assert result.graders["refusal"].regressed == ["a"] and result.graders["advice"].fixed == ["a"]


def test_for_version_filters():
    records = [g("a", True), g("a", True, "v2")]
    assert [r.version for r in for_version(records, "v2")] == ["v2"]
