import pytest

from evalpilot.models import Case, Doc, GradeRecord, Trace, ValidationError

BASE_CASE = {
    "id": "x_01",
    "query": "What is NAV?",
    "category": "in_scope_fact",
    "in_scope": True,
    "should_refuse": False,
}


def test_case_minimal_defaults():
    case = Case.from_dict(BASE_CASE)
    assert case.gold_entity is None and case.gold_fee is None and case.required_doc_ids == []


@pytest.mark.parametrize(
    "patch, message",
    [
        ({"category": "vibes"}, "unknown category"),
        ({"in_scope": "yes"}, "must be bool"),
        ({"category": "out_of_scope"}, "out_of_scope cases need"),
        ({"in_scope": False}, "only out_of_scope"),
        ({"gold_fee": {"expense_ratio_direct": "0.6"}}, "must be a number"),
        ({"gold_fee": {}}, "non-empty"),
        ({"surprise": 1}, "unknown field"),
    ],
)
def test_case_validation_errors(patch, message):
    with pytest.raises(ValidationError, match=message):
        Case.from_dict({**BASE_CASE, **patch})


def test_case_missing_field():
    data = dict(BASE_CASE)
    del data["query"]
    with pytest.raises(ValidationError, match="missing field 'query'"):
        Case.from_dict(data)


def test_doc_rejects_unknown_source():
    with pytest.raises(ValidationError, match="source"):
        Doc(doc_id="d", title="t", text="body", source="rumour")


def _trace(**overrides):
    data = dict(
        run_id="r", case_id="c", version="v1", query="q", retrieved_doc_ids=[],
        answer="a", citations=[], refused=False, model="m", provider="offline",
    )
    return Trace(**{**data, **overrides})


def test_trace_round_trip():
    trace = _trace()
    assert Trace.from_dict(trace.to_dict()) == trace


def test_trace_rejects_unknown_version():
    with pytest.raises(ValidationError, match="version"):
        _trace(version="v9")


def test_grade_must_be_binary():
    with pytest.raises(ValidationError, match="binary"):
        GradeRecord(run_id="r", case_id="c", version="v1", grader="advice", passed=4, evidence="", kind="code")


def test_grade_kind_checked():
    with pytest.raises(ValidationError, match="kind"):
        GradeRecord(run_id="r", case_id="c", version="v1", grader="advice", passed=True, evidence="", kind="vibes")
