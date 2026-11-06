from evalpilot.bot.retriever import EntityAwareRetriever, NaiveRetriever, retriever_for, tokenize


def test_tokenize_stems_and_drops_stopwords():
    assert tokenize("What returns are guaranteed?") == ["return", "guarante"]
    assert tokenize("guarantee") == ["guarante"]


def test_naive_returns_top_k_chunks(naive):
    retrieval = naive.retrieve("expense ratio Bluechip Growth direct plan")
    assert 1 <= len(retrieval.chunks) <= 4
    assert retrieval.doc_ids[0] == "bluechip_growth_factsheet"
    assert retrieval.entities == []


def test_naive_includes_scraped_for_injection_bait(naive, cases_by_id):
    for case_id in ("inj_01", "inj_02", "inj_03", "inj_04"):
        doc_ids = naive.retrieve(cases_by_id[case_id].query).doc_ids
        assert any(d.startswith("scraped_") for d in doc_ids), case_id


def test_entity_aware_excludes_scraped_everywhere(entity_aware, dataset):
    for case in dataset.cases:
        assert not any(d.startswith("scraped_") for d in entity_aware.retrieve(case.query).doc_ids), case.id


def test_entity_aware_filters_to_gold_entity(entity_aware, dataset, kb):
    for case in dataset.cases:
        if case.category == "entity_confusion":
            retrieval = entity_aware.retrieve(case.query)
            assert retrieval.entities == [case.gold_entity]
            assert {kb.doc(d).entity for d in retrieval.doc_ids} == {case.gold_entity}, case.id


def test_entity_aware_gives_each_entity_context(entity_aware):
    retrieval = entity_aware.retrieve("Is Bluechip Growth better than Bluechip Value for me?")
    assert set(retrieval.doc_ids) == {"bluechip_growth_factsheet", "bluechip_value_factsheet"}


def test_entity_aware_falls_back_without_entity(entity_aware):
    retrieval = entity_aware.retrieve("What is the cut-off time to get same-day NAV?")
    assert retrieval.entities == []
    assert "account_services" in retrieval.doc_ids


def test_naive_confuses_siblings_somewhere(naive, dataset, kb):
    """v1/v2 retrieval pulls sibling-fund docs for at least one entity_confusion case (the bug v3 fixes)."""
    confused = [
        c.id for c in dataset.cases
        if c.category == "entity_confusion"
        and any(kb.doc(d).entity not in (None, c.gold_entity) for d in naive.retrieve(c.query).doc_ids)
    ]
    assert confused


def test_retriever_for_version(kb):
    assert isinstance(retriever_for("v1", kb), NaiveRetriever)
    assert isinstance(retriever_for("v2", kb), NaiveRetriever)
    assert isinstance(retriever_for("v3", kb), EntityAwareRetriever)


def test_no_match_returns_nothing(naive):
    assert naive.retrieve("zzz qqq").chunks == []
