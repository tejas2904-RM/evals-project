import json

import pytest
from conftest import FakeTransport

from evalpilot.bot.bot import run_case
from evalpilot.bot.guardrails import REFUSAL
from evalpilot.bot.retriever import retriever_for
from evalpilot.llm import LlmClient
from evalpilot.models import Trace
from evalpilot.patterns import find_advice, find_unsafe_claim
from evalpilot.runner import execute_run


@pytest.fixture
def offline_run(settings, dataset):
    client = LlmClient(settings, "offline")
    result = execute_run(settings, client, dataset.cases, dataset.docs, ["v1", "v2", "v3"], run_id="test-run")
    return {(t.version, t.case_id): t for t in result.traces}, result


def _by(traces, version, category, dataset):
    ids = {c.id for c in dataset.cases if c.category == category}
    return [t for (v, cid), t in traces.items() if v == version and cid in ids]


def test_run_all_versions_offline(offline_run):
    traces, result = offline_run
    assert len(traces) == 123 and result.complete
    assert all(t.provider == "offline" and t.cost_usd == 0 for t in traces.values())


def test_traces_persisted_and_round_trip(offline_run):
    traces, result = offline_run
    lines = (result.path / "traces.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 123
    assert Trace.from_dict(json.loads(lines[0])) in traces.values()
    meta = json.loads((result.path / "meta.json").read_text(encoding="utf-8"))
    assert meta["n_traces"] == 123 and meta["complete"] and meta["cost_usd"] == 0


def test_v1_applies_no_guardrails(offline_run):
    traces, _ = offline_run
    for (version, _), t in traces.items():
        if version == "v1":
            assert t.guardrails == [] and t.answer == t.raw_answer


def test_v1_answers_out_of_scope(offline_run, dataset):
    traces, _ = offline_run
    assert not any(t.refused for t in _by(traces, "v1", "out_of_scope", dataset))


def test_guarded_versions_refuse_out_of_scope_without_model_call(offline_run, dataset):
    traces, _ = offline_run
    for version in ("v2", "v3"):
        for t in _by(traces, version, "out_of_scope", dataset):
            assert t.refused and t.answer == REFUSAL and t.guardrails == ["scope_gate"] and t.model == "guardrail"


def test_v1_lacks_citations_on_citation_required(offline_run, dataset):
    traces, _ = offline_run
    assert all(t.citations == [] for t in _by(traces, "v1", "citation_required", dataset))


def test_v1_exhibits_advice_and_unsafe_claims(offline_run, dataset):
    traces, _ = offline_run
    assert all(find_advice(t.answer) for t in _by(traces, "v1", "advice_bait", dataset))
    assert all(find_unsafe_claim(t.answer) for t in _by(traces, "v1", "injection_bait", dataset))


def test_guarded_versions_never_ship_advice_or_unsafe_claims(offline_run):
    traces, _ = offline_run
    for (version, case_id), t in traces.items():
        if version in ("v2", "v3"):
            assert not find_advice(t.answer), case_id
            assert not find_unsafe_claim(t.answer), case_id


def test_v2_guardrails_catch_model_slips(offline_run):
    traces, _ = offline_run
    assert "advice_filter" in traces[("v2", "adv_01")].guardrails
    assert "unsafe_filter" in traces[("v2", "inj_01")].guardrails
    assert "citation_fix" in traces[("v2", "fact_04")].guardrails


def test_guarded_citations_are_always_retrieved(offline_run):
    traces, _ = offline_run
    for (version, case_id), t in traces.items():
        if version in ("v2", "v3"):
            assert set(t.citations) <= set(t.retrieved_doc_ids), case_id


def test_guarded_non_refusals_always_cite(offline_run):
    traces, _ = offline_run
    for (version, case_id), t in traces.items():
        if version in ("v2", "v3") and not t.refused:
            assert t.citations, case_id


def test_v2_still_confuses_entities_v3_does_not(offline_run, dataset, kb):
    traces, _ = offline_run
    for case in dataset.cases:
        if case.category != "entity_confusion":
            continue
        gold_name = kb.entity_names[case.gold_entity]
        assert gold_name not in traces[("v2", case.id)].answer, case.id
        assert gold_name in traces[("v3", case.id)].answer, case.id


def test_v3_entity_confusion_retrieves_only_gold(offline_run, dataset, kb):
    traces, _ = offline_run
    for case in dataset.cases:
        if case.category == "entity_confusion":
            t = traces[("v3", case.id)]
            assert t.entities == [case.gold_entity]
            assert {kb.doc(d).entity for d in t.retrieved_doc_ids} == {case.gold_entity}


def test_offline_fixtures_cover_every_model_call(settings, dataset):
    keys = {json.loads(line)["key"] for line in settings.provider("offline").fixtures.open(encoding="utf-8")}
    for case in dataset.cases:
        assert f"v1:{case.id}" in keys
        if case.category != "out_of_scope":
            assert f"v2:{case.id}" in keys and f"v3:{case.id}" in keys


def test_paid_run_case_is_billed_then_cached(settings, dataset, kb, cases_by_id):
    transport = FakeTransport(content="The Direct Plan expense ratio is 0.62% [bluechip_growth_factsheet].")
    client = LlmClient(settings, "openai", transport=transport)
    retriever = retriever_for("v3", kb)
    first = run_case(cases_by_id["fee_01"], "v3", client, kb, retriever, "r1")
    second = run_case(cases_by_id["fee_01"], "v3", client, kb, retriever, "r2")

    assert first.cost_usd > 0 and not first.cached
    assert second.cached and second.cost_usd == 0
    assert len(transport.requests) == 1
    sent = transport.requests[0]
    assert sent["model"] == "gpt-5.4-nano" and "temperature" not in sent
    assert "[bluechip_growth_factsheet]" in sent["messages"][1]["content"]
    assert "Asterion Bluechip Growth Fund" in sent["messages"][0]["content"]


def test_scope_gate_makes_no_model_call(settings, kb, cases_by_id):
    transport = FakeTransport()
    client = LlmClient(settings, "openai", transport=transport)
    trace = run_case(cases_by_id["oos_01"], "v2", client, kb, retriever_for("v2", kb), "r")
    assert trace.refused and transport.requests == []
