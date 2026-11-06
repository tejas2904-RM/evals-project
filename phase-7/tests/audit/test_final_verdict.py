import pytest

from evalpilot.audit.models import Verdict
from evalpilot.audit.verdict import final_decision

VIOLATION = {"grader": "judge_grounded", "rule": "regressions_vs_v2", "threshold": "<= 0", "observed": "1", "case_ids": ["adv_05"]}


def gate(verdict: str) -> dict:
    return {"verdict": verdict, "violations": [VIOLATION] if verdict == "BLOCKED" else []}


def audit(decision: str) -> Verdict:
    blocked = decision == "BLOCK"
    return Verdict(
        decision=decision,
        deciding_risks=["R-1"] if blocked else [],
        reasons=["1 open high risk(s) > max_open_high=0"] if blocked else ["no open critical/high risks"],
        conditions=[] if blocked else ["accept R-2 (medium) before launch"],
        counts={"critical": 0, "high": int(blocked), "medium": 1, "low": 0, "accepted": 0},
    )


@pytest.mark.parametrize(
    ("gate_verdict", "audit_decision", "expected"),
    [
        ("PASS", "SHIP", "SHIP"),
        ("PASS", "BLOCK", "BLOCK"),
        ("BLOCKED", "SHIP", "BLOCK"),
        ("BLOCKED", "BLOCK", "BLOCK"),
        ("PASS", None, "BLOCK"),
        ("BLOCKED", None, "BLOCK"),
    ],
)
def test_ship_only_when_gate_passes_and_audit_ships(gate_verdict, audit_decision, expected):
    a = audit(audit_decision) if audit_decision else None
    final = final_decision(gate(gate_verdict), a, version="v3", run_id="r", audit_id="aud" if a else None)
    assert final.decision == expected
    assert final.gate_verdict == gate_verdict and final.audit_decision == audit_decision


def test_block_names_the_deciding_rules_and_risks():
    final = final_decision(gate("BLOCKED"), audit("BLOCK"), version="v3", run_id="r", audit_id="aud")
    assert final.deciding_rules == ["judge_grounded | regressions_vs_v2 | <= 0 | 1 | adv_05"]
    assert final.deciding_risks == ["R-1"]
    assert any("release gate v3: BLOCKED" in r for r in final.reasons)
    assert any(r.startswith("audit aud: BLOCK") for r in final.reasons)


def test_missing_audit_says_how_to_get_one():
    final = final_decision(gate("PASS"), None, version="v3", run_id="r", audit_id=None)
    assert any("--trace-version" in r for r in final.reasons)


def test_ship_carries_audit_conditions():
    final = final_decision(gate("PASS"), audit("SHIP"), version="v3", run_id="r", audit_id="aud")
    assert final.conditions == ["accept R-2 (medium) before launch"] and not final.deciding_rules
