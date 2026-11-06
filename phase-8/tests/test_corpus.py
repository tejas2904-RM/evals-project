import re

import pytest

from evalpilot.data import parse_doc
from evalpilot.models import ValidationError

FEE_FIELDS = {"expense_ratio_direct", "expense_ratio_regular", "exit_load_pct", "exit_load_days"}
UNSAFE = re.compile(r"guarantee|assured|risk-free|no risk", re.IGNORECASE)


def test_corpus_size(dataset):
    assert 8 <= len(dataset.docs) <= 12


def test_entity_docs_have_fee_fields(dataset):
    for doc in dataset.docs:
        if doc.entity and doc.source == "official":
            assert FEE_FIELDS <= set(doc.fields), doc.doc_id
            assert doc.aliases, doc.doc_id


def test_corpus_contains_injected_scraped_docs(dataset):
    scraped = [d for d in dataset.docs if d.source == "scraped"]
    assert scraped
    assert all(UNSAFE.search(d.text) for d in scraped)


def test_official_docs_never_claim_guarantees(dataset):
    for doc in dataset.docs:
        if doc.source == "official":
            for match in UNSAFE.finditer(doc.text):
                before = doc.text[max(0, match.start() - 12) : match.start()].lower()
                assert "not" in before or "no " in before, f"{doc.doc_id}: '{match.group()}'"


def test_alias_map_from_official_docs_only(dataset):
    aliases = dataset.alias_map()
    assert aliases["bluechip value"] == "bluechip_value"
    assert aliases["bluechip growth"] == "bluechip_growth"
    assert len(set(aliases.values())) == 7


def test_aliases_are_unambiguous(dataset):
    seen: dict[str, str] = {}
    for doc in dataset.docs:
        if doc.source != "official":
            continue
        for alias in doc.aliases:
            key = alias.lower()
            assert seen.get(key, doc.entity) == doc.entity, f"alias '{alias}' maps to two entities"
            seen[key] = doc.entity


def test_parse_doc_front_matter():
    doc = parse_doc("---\ndoc_id: d1\ntitle: T\nentity: e\naliases: A, B\nfee.exit_load_pct: 1\n---\nBody", "d1.md")
    assert doc.doc_id == "d1" and doc.aliases == ["A", "B"] and doc.fields == {"exit_load_pct": 1.0}
    assert doc.text == "Body"


@pytest.mark.parametrize(
    "text, message",
    [
        ("no front matter", "missing front-matter"),
        ("---\ndoc_id: d\n", "unterminated"),
        ("---\ndoc_id: d\ntitle: t\nfee.x: abc\n---\nbody", "numeric"),
    ],
)
def test_parse_doc_errors(text, message):
    with pytest.raises(ValidationError, match=message):
        parse_doc(text)
