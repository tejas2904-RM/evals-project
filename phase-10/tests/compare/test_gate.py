import pytest

from evalpilot.compare import default_baseline, evaluate_gate
from evalpilot.config import ConfigError, GateConfig, load_settings
from evalpilot.models import GradeRecord

CFG = GateConfig(
    min_pass_rate={"refusal": 0.9, "wrong_entity": 0.9},
    max_regressions_per_grader=0,
    required_improvements={"v2_over_v1": ["refusal"], "v3_over_v2": ["wrong_entity"]},
)


def g(case_id, passed, version, grader="refusal", evidence="e"):
    return GradeRecord("r", case_id, version, grader, passed, evidence, "code")


def grades(version, grader, passes, n=10):
    return [g(f"{grader[:3]}_{i:02d}", i < passes, version, grader) for i in range(n)]


def test_default_baseline_is_previous_version():
    assert [default_baseline(v) for v in ("v1", "v2", "v3")] == [None, "v1", "v2"]


def test_min_pass_rate_violation_names_failing_cases():
    result = evaluate_gate(grades("v1", "refusal", 7) + grades("v1", "wrong_entity", 10), "v1", CFG)
    assert result.verdict == "BLOCKED"
    [v] = result.violations
    assert (v.grader, v.rule, v.threshold, v.observed) == ("refusal", "min_pass_rate", ">= 90%", "7/10 (70%)")
    assert v.case_ids == ["ref_07", "ref_08", "ref_09"]
    assert v.line() == "refusal | min_pass_rate | >= 90% | 7/10 (70%) | ref_07, ref_08, ref_09"


def test_passing_version():
    records = grades("v2", "refusal", 9) + grades("v2", "wrong_entity", 9) + grades("v3", "refusal", 9) + grades("v3", "wrong_entity", 10)
    result = evaluate_gate(records, "v3", CFG, baseline="v2")
    assert result.passed and result.violations == []


def test_single_regression_blocks_with_case_id():
    base = grades("v2", "refusal", 10) + grades("v2", "wrong_entity", 9)
    cand = [g(r.case_id, r.case_id != "ref_03", "v3") for r in grades("v3", "refusal", 10)] + grades("v3", "wrong_entity", 10)
    result = evaluate_gate(base + cand, "v3", CFG, baseline="v2")
    [v] = result.violations
    assert (v.grader, v.rule, v.threshold, v.observed, v.case_ids) == ("refusal", "regressions_vs_v2", "<= 0", "1", ["ref_03"])


def test_swapped_cases_count_as_a_regression_even_at_equal_rates():
    base = [g("a", True, "v2"), g("b", False, "v2")]
    cand = [g("a", False, "v3"), g("b", True, "v3")]
    result = evaluate_gate(base + cand, "v3", GateConfig(), baseline="v2")
    assert [v.case_ids for v in result.violations] == [["a"]]


def test_required_improvement_needs_strictly_more_passes():
    records = grades("v1", "refusal", 9) + grades("v2", "refusal", 9) + grades("v1", "wrong_entity", 9) + grades("v2", "wrong_entity", 9)
    result = evaluate_gate(records, "v2", CFG, baseline="v1")
    [v] = result.violations
    assert (v.grader, v.rule, v.observed) == ("refusal", "improvement_over_v1", "9 passes (9/10 (90%))")
    assert v.threshold.startswith("> 9 passes (v1")
    assert v.case_ids == ["ref_09"]


def test_required_improvement_at_ceiling_becomes_no_regression():
    records = grades("v2", "refusal", 10) + grades("v2", "wrong_entity", 10)
    records += grades("v3", "refusal", 10) + grades("v3", "wrong_entity", 10)
    result = evaluate_gate(records, "v3", CFG, baseline="v2")
    assert result.passed
    assert any("already passes 10/10" in w and "no regression" in w for w in result.warnings)


def test_ceiling_still_blocks_a_regression():
    records = grades("v2", "refusal", 10) + grades("v2", "wrong_entity", 10)
    records += grades("v3", "refusal", 10) + grades("v3", "wrong_entity", 9)
    result = evaluate_gate(records, "v3", CFG, baseline="v2")
    assert [(v.grader, v.rule) for v in result.violations] == [("wrong_entity", "regressions_vs_v2")]


def test_na_excluded_and_all_na_warns():
    records = [g(f"c{i}", True, "v1", "wrong_entity", "n/a: no entity") for i in range(3)] + grades("v1", "refusal", 10)
    result = evaluate_gate(records, "v1", CFG)
    assert result.passed
    assert any("wrong_entity: no applicable cases" in w for w in result.warnings)


def test_missing_grader_is_a_violation():
    result = evaluate_gate(grades("v1", "refusal", 10), "v1", CFG)
    assert [(v.grader, v.rule) for v in result.violations] == [("wrong_entity", "missing_grades")]


def test_unknown_version_and_grader():
    with pytest.raises(ValueError, match="no grades for version v3"):
        evaluate_gate(grades("v1", "refusal", 10), "v3", CFG)
    with pytest.raises(ConfigError, match="unknown grader"):
        evaluate_gate(grades("v1", "refusal", 10), "v1", GateConfig(min_pass_rate={"nope": 0.5}))


def test_gate_config_from_evals_toml(settings):
    cfg = settings.gate
    assert cfg.min_pass_rate["unsafe_claim"] == 1.0 and len(cfg.min_pass_rate) == 8
    assert cfg.max_regressions_per_grader == 0
    assert cfg.required_improvements == {
        "v2_over_v1": ["refusal", "advice", "unsafe_claim", "citation"],
        "v3_over_v2": ["wrong_entity"],
    }


@pytest.mark.parametrize("extra, message", [
    ("[gate.required_improvements]\nv3_beats_v2 = []\n", "must look like v2_over_v1"),
    ("[gate]\nmin_pass_rate = { refusal = 1.5 }\n", "min_pass_rate"),
    ("[gate]\nmax_regressions_per_grader = -1\n", "max_regressions_per_grader"),
    ("[gate]\nthreshold = 1\n", "unknown \\[gate\\]"),
])
def test_gate_config_validation(tmp_project, extra, message):
    path = tmp_project / "evals.toml"
    text = path.read_text(encoding="utf-8")
    start = text.index("[gate]")
    end = text.index("# Judge calibration")
    path.write_text(text[:start] + extra + "\n" + text[end:], encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_settings(tmp_project)
