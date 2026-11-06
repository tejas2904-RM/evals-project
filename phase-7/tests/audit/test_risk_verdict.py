from dataclasses import replace
from datetime import date

import pytest
from audit_helpers import finding

from evalpilot.audit.models import risk_id_for
from evalpilot.audit.risk import AcceptanceError, build_register, level_for, load_acceptances, number_findings
from evalpilot.audit.verdict import decide


@pytest.mark.parametrize("severity,level", [(25, "critical"), (20, "critical"), (19, "high"), (12, "high"),
                                            (11, "medium"), (6, "medium"), (5, "low"), (1, "low")])
def test_level_boundaries(audit_cfg, severity, level):
    assert level_for(severity, audit_cfg) == level


def test_severity_is_likelihood_times_impact(audit_cfg):
    [risk] = build_register([finding(likelihood=4, impact=5)], audit_cfg)
    assert (risk.likelihood, risk.impact, risk.severity, risk.level) == (4, 5, 20, "critical")


def test_findings_with_same_root_cause_merge_into_one_risk(audit_cfg):
    findings = number_findings([
        finding("exec:tools.py", likelihood=4, impact=5, check_id="code/llm-output-eval", location="tools.py:10"),
        finding("exec:tools.py", likelihood=3, impact=4, check_id="bandit/B307", source="tool", location="tools.py:10"),
        finding("other:x.py", location="x.py:2"),
    ])
    risks = build_register(findings, audit_cfg)
    assert len(risks) == 2
    top = risks[0]
    assert top.check_ids == ["bandit/B307", "code/llm-output-eval"]
    assert top.findings == ["F-001", "F-002"]
    assert len(top.evidence) == 1  # same location deduped
    assert top.severity == 20


def test_ai_finding_corroborated_by_rule_gains_likelihood(audit_cfg):
    alone = build_register([finding("k", likelihood=3, impact=4, source="ai")], audit_cfg)[0]
    both = build_register([finding("k", likelihood=3, impact=4, source="ai"), finding("k", likelihood=3, impact=4)], audit_cfg)[0]
    assert alone.likelihood == 3 and both.likelihood == 4


def test_uncorroborated_ai_risk_is_capped_and_cannot_block(audit_cfg):
    [risk] = build_register([finding("ai:x.py:3", likelihood=3, impact=5, source="ai")], audit_cfg)
    assert (risk.severity, risk.level, risk.capped_from) == (15, "medium", "high")
    v = decide([risk], audit_cfg)
    assert v.decision == "SHIP" and "AI-only, capped from high" in v.conditions[0]


def test_corroborated_ai_risk_keeps_full_level(audit_cfg):
    [risk] = build_register([finding("k", likelihood=3, impact=5, source="ai"), finding("k", likelihood=3, impact=5)], audit_cfg)
    assert risk.level == "critical" and risk.capped_from is None


def test_ai_cap_is_configurable(audit_cfg):
    [risk] = build_register([finding("ai:x", likelihood=3, impact=5, source="ai")], replace(audit_cfg, ai_only_max_level="critical"))
    assert risk.level == "high" and risk.capped_from is None


def test_ai_cap_config_is_validated(tmp_project):
    from evalpilot.config import ConfigError, load_settings

    path = tmp_project / "evals.toml"
    path.write_text(path.read_text(encoding="utf-8").replace('ai_only_max_level = "medium"', 'ai_only_max_level = "severe"'),
                    encoding="utf-8")
    with pytest.raises(ConfigError, match="ai_only_max_level"):
        load_settings(tmp_project)


def test_risk_ids_are_stable_across_audits(audit_cfg):
    assert build_register([finding("secret:config.py")], audit_cfg)[0].risk_id == risk_id_for("secret:config.py")
    assert risk_id_for("a") != risk_id_for("b")


def test_register_sorted_by_severity(audit_cfg):
    risks = build_register([finding("a", likelihood=1, impact=1), finding("b", likelihood=5, impact=5), finding("c", likelihood=3, impact=3)], audit_cfg)
    assert [r.severity for r in risks] == [25, 9, 1]


def test_verdict_blocks_on_open_critical(audit_cfg):
    v = decide(build_register([finding("a", likelihood=5, impact=4)], audit_cfg), audit_cfg)
    assert v.decision == "BLOCK" and v.deciding_risks == [risk_id_for("a")]


def test_verdict_blocks_on_high_above_threshold(audit_cfg):
    risks = build_register([finding("a", likelihood=4, impact=3)], audit_cfg)
    assert decide(risks, audit_cfg).decision == "BLOCK"
    assert decide(risks, replace(audit_cfg, max_open_high=1)).decision == "SHIP"


def test_verdict_ships_with_conditions_for_mediums(audit_cfg):
    v = decide(build_register([finding("a", likelihood=3, impact=3), finding("b", likelihood=1, impact=2)], audit_cfg), audit_cfg)
    assert v.decision == "SHIP"
    assert len(v.conditions) == 1 and v.counts["medium"] == 1 and v.counts["low"] == 1


def test_accepted_risk_does_not_block_until_expiry(tmp_path, audit_cfg):
    rid = risk_id_for("a")
    path = tmp_path / "acc.toml"
    path.write_text(f'[[accept]]\nrisk_id = "{rid}"\nowner = "cto"\nreason = "compensating control"\nexpires = 2027-01-01\n', encoding="utf-8")
    acc = load_acceptances(path)
    findings = [finding("a", likelihood=5, impact=5)]
    ok = decide(build_register(findings, audit_cfg, acc, today=date(2026, 12, 31)), audit_cfg)
    assert ok.decision == "SHIP" and ok.counts["accepted"] == 1 and "accepted by cto" in ok.conditions[0]
    late = decide(build_register(findings, audit_cfg, acc, today=date(2027, 1, 2)), audit_cfg)
    assert late.decision == "BLOCK"


def test_acceptance_requires_owner_reason_expiry(tmp_path):
    path = tmp_path / "acc.toml"
    path.write_text('[[accept]]\nrisk_id = "R-1"\nowner = "me"\n', encoding="utf-8")
    with pytest.raises(AcceptanceError, match="missing"):
        load_acceptances(path)
