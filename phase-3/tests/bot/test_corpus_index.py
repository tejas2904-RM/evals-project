from evalpilot.bot.corpus import chunk_doc


def test_chunks_split_on_headings(dataset):
    doc = next(d for d in dataset.docs if d.doc_id == "bluechip_growth_factsheet")
    chunks = chunk_doc(doc)
    assert len(chunks) == 5
    assert all(c.doc_id == doc.doc_id and c.title == doc.title for c in chunks)
    assert any("0.62%" in c.text for c in chunks)


def test_every_doc_has_chunks(kb, dataset):
    assert {c.doc_id for c in kb.chunks} == {d.doc_id for d in dataset.docs}


def test_longest_alias_wins(kb):
    assert kb.detect_entities("Bluechip Value Fund minimum SIP") == ["bluechip_value"]
    assert kb.detect_entities("Horizon Short Term Debt Fund exit load") == ["horizon_short_term"]
    assert kb.detect_entities("Horizon Debt Fund exit load") == ["horizon_debt"]


def test_multiple_entities_in_order(kb):
    assert kb.detect_entities("Is Bluechip Growth better than Bluechip Value?") == ["bluechip_growth", "bluechip_value"]


def test_no_entity(kb):
    assert kb.detect_entities("What is an exit load?") == []


def test_scraped_docs_contribute_no_aliases(kb):
    assert set(kb.aliases.values()) == set(kb.entity_names)
    assert len(kb.entity_names) == 7
