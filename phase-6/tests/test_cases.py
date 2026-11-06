from collections import Counter

import pytest

from evalpilot.data import load_cases
from evalpilot.models import ValidationError

EXPECTED_DISTRIBUTION = {
    "in_scope_fact": 8,
    "fee": 7,
    "out_of_scope": 7,
    "advice_bait": 6,
    "injection_bait": 5,
    "entity_confusion": 5,
    "citation_required": 3,
}


def test_cases_count_is_41(dataset):
    assert len(dataset.cases) == 41


def test_case_ids_unique(dataset):
    ids = [c.id for c in dataset.cases]
    assert len(ids) == len(set(ids))


def test_case_category_distribution(dataset):
    assert Counter(c.category for c in dataset.cases) == EXPECTED_DISTRIBUTION


def test_case_references_resolve(dataset):
    assert dataset.check_references() == []


def test_out_of_scope_cases_need_no_docs(dataset):
    for case in dataset.cases:
        if case.category == "out_of_scope":
            assert case.required_doc_ids == [] and case.gold_entity is None


def test_fee_cases_have_gold_fee_and_entity(dataset):
    for case in dataset.cases:
        if case.category == "fee":
            assert case.gold_fee and case.gold_entity, case.id


def test_citation_cases_require_docs(dataset):
    for case in dataset.cases:
        if case.category in {"citation_required", "fee", "injection_bait", "entity_confusion"}:
            assert case.required_doc_ids, case.id


def test_entity_confusion_targets_have_a_sibling(dataset):
    """Each confusable entity shares a name prefix with another fund, so confusion is possible."""
    entities = dataset.entities
    for case in dataset.cases:
        if case.category == "entity_confusion":
            prefix = case.gold_entity.split("_")[0]
            assert len([e for e in entities if e.startswith(prefix)]) >= 2, case.id


def test_duplicate_case_id_rejected(tmp_path):
    line = '{"id": "a", "query": "q", "category": "fee", "in_scope": true, "should_refuse": false}\n'
    path = tmp_path / "cases.jsonl"
    path.write_text(line * 2, encoding="utf-8")
    with pytest.raises(ValidationError, match="duplicate"):
        load_cases(path)


def test_bad_json_reports_line_number(tmp_path):
    path = tmp_path / "cases.jsonl"
    path.write_text("{not json}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="cases.jsonl:1"):
        load_cases(path)
