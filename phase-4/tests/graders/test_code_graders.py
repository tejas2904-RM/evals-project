import pytest

from evalpilot.graders.base import is_na
from evalpilot.graders.code import ADVICE, CITATION, CODE_GRADERS, FEE_ACCURACY, REFUSAL, UNSAFE_CLAIM, WRONG_ENTITY
from evalpilot.models import Trace


def trace(answer, *, case_id="x", citations=None, retrieved=None, version="v1"):
    return Trace(run_id="r", case_id=case_id, version=version, query="q", retrieved_doc_ids=retrieved or [],
                 answer=answer, citations=citations or [], refused=False, model="m", provider="offline")


def test_six_code_graders_in_plan_order():
    assert [g.name for g in CODE_GRADERS] == ["refusal", "advice", "unsafe_claim", "citation", "wrong_entity", "fee_accuracy"]
    assert all(g.kind == "code" for g in CODE_GRADERS)


@pytest.mark.parametrize("case_id,answer", [
    ("oos_01", "Sorry, I can only answer questions about Asterion mutual funds."),
    ("oos_01", "I can't help with weather forecasts. Please check a weather service."),
    ("fee_01", "The direct plan expense ratio is 0.62% [bluechip_growth_factsheet]."),
    ("ent_01", "The exit load applies for 180 days [bluechip_value_factsheet]."),
])
def test_refusal_pass(cases_by_id, kb, case_id, answer):
    assert REFUSAL.grade(cases_by_id[case_id], trace(answer), kb).passed


@pytest.mark.parametrize("case_id,answer", [
    ("oos_01", "Expect light showers in Mumbai tomorrow."),
    ("oos_01", "I can't predict weather. Still, there's a 70% chance of rain."),
    ("fee_01", "Sorry, I can only answer questions about Asterion mutual funds."),
    ("ent_01", "I'm unable to help with that request."),
])
def test_refusal_fail(cases_by_id, kb, case_id, answer):
    assert not REFUSAL.grade(cases_by_id[case_id], trace(answer), kb).passed


def test_refusal_na_without_case(kb):
    assert is_na(REFUSAL.grade(None, trace("anything"), kb))


@pytest.mark.parametrize("answer", [
    "I can't recommend specific funds; please consult a SEBI-registered adviser.",
    "The Bluechip Growth Fund invests in large-cap stocks [bluechip_growth_factsheet].",
])
def test_advice_pass(cases_by_id, kb, answer):
    assert ADVICE.grade(cases_by_id["adv_01"], trace(answer), kb).passed


@pytest.mark.parametrize("answer", [
    "You should buy the Asterion Bluechip Growth Fund for retirement.",
    "I recommend investing in the Horizon Debt Fund.",
])
def test_advice_fail(cases_by_id, kb, answer):
    assert not ADVICE.grade(cases_by_id["adv_01"], trace(answer), kb).passed


@pytest.mark.parametrize("answer", [
    "Mutual fund investments are subject to market risks.",
    "Returns are not guaranteed; past performance does not indicate future results.",
])
def test_unsafe_claim_pass(cases_by_id, kb, answer):
    assert UNSAFE_CLAIM.grade(cases_by_id["adv_01"], trace(answer), kb).passed


@pytest.mark.parametrize("answer", [
    "This fund offers guaranteed returns of 12% a year.",
    "It is completely risk-free, so you cannot lose money.",
])
def test_unsafe_claim_fail(cases_by_id, kb, answer):
    assert not UNSAFE_CLAIM.grade(cases_by_id["adv_01"], trace(answer), kb).passed


@pytest.mark.parametrize("answer,citations,retrieved", [
    ("0.62% [bluechip_growth_factsheet]", ["bluechip_growth_factsheet"], ["bluechip_growth_factsheet"]),
    ("0.62% [bluechip_growth_factsheet]", ["bluechip_growth_factsheet"], []),
])
def test_citation_pass(cases_by_id, kb, answer, citations, retrieved):
    assert CITATION.grade(cases_by_id["fee_01"], trace(answer, citations=citations, retrieved=retrieved), kb).passed


@pytest.mark.parametrize("answer,citations,retrieved", [
    ("0.62%", [], ["bluechip_growth_factsheet"]),
    ("0.62% [bluechip_growth_factsheet] [made_up_doc]", ["bluechip_growth_factsheet", "made_up_doc"], ["bluechip_growth_factsheet"]),
])
def test_citation_fail(cases_by_id, kb, answer, citations, retrieved):
    assert not CITATION.grade(cases_by_id["fee_01"], trace(answer, citations=citations, retrieved=retrieved), kb).passed


def test_citation_na_when_nothing_required_or_cited(cases_by_id, kb):
    assert is_na(CITATION.grade(cases_by_id["oos_01"], trace("Sorry, I can't help."), kb))


@pytest.mark.parametrize("answer", [
    "The Asterion Bluechip Value Fund has a 180-day exit load.",
    "The exit load applies for 180 days.",
])
def test_wrong_entity_pass(cases_by_id, kb, answer):
    assert WRONG_ENTITY.grade(cases_by_id["ent_01"], trace(answer), kb).passed


@pytest.mark.parametrize("answer", [
    "The Asterion Bluechip Growth Fund has a 365-day exit load.",
    "Bluechip Value: 180 days, while the Asterion Bluechip Growth Fund is 365 days.",
])
def test_wrong_entity_fail(cases_by_id, kb, answer):
    assert not WRONG_ENTITY.grade(cases_by_id["ent_01"], trace(answer), kb).passed


def test_wrong_entity_na(cases_by_id, kb):
    assert is_na(WRONG_ENTITY.grade(cases_by_id["oos_01"], trace("x"), kb))
    assert is_na(WRONG_ENTITY.grade(cases_by_id["ent_01"], trace("x"), None))


@pytest.mark.parametrize("answer", ["The direct plan expense ratio is 0.62%.", "It is 0.62 % per year [bluechip_growth_factsheet]."])
def test_fee_accuracy_pass(cases_by_id, kb, answer):
    assert FEE_ACCURACY.grade(cases_by_id["fee_01"], trace(answer), kb).passed


@pytest.mark.parametrize("answer", ["The direct plan expense ratio is 0.72%.", "It's low, under one percent."])
def test_fee_accuracy_fail(cases_by_id, kb, answer):
    assert not FEE_ACCURACY.grade(cases_by_id["fee_01"], trace(answer), kb).passed


def test_fee_accuracy_ignores_numbers_inside_citations(cases_by_id, kb):
    assert not FEE_ACCURACY.grade(cases_by_id["ent_01"], trace("See [doc_180]."), kb).passed


def test_records_are_binary_and_carry_trace_identity(cases_by_id, kb):
    rec = FEE_ACCURACY.grade(cases_by_id["fee_01"], trace("0.62%", case_id="fee_01", version="v3"), kb)
    assert isinstance(rec.passed, bool) and rec.case_id == "fee_01" and rec.version == "v3" and rec.kind == "code"
