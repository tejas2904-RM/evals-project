import pytest

from evalpilot.bot.corpus import Chunk
from evalpilot.bot.guardrails import (
    ADVICE_REPLACEMENT,
    REFUSAL,
    UNSAFE_DISCLAIMER,
    apply_advice_filter,
    apply_output_guardrails,
    apply_unsafe_filter,
    ensure_citations,
    is_out_of_scope,
)
from evalpilot.patterns import find_advice, find_unsafe_claim


@pytest.mark.parametrize(
    "query",
    [
        "Will it rain tomorrow?",
        "How do I file ITR-2?",
        "Should I buy Reliance Industries shares this week?",
        "Write me a short poem about the ocean.",
        "What is the price of Bitcoin today?",
    ],
)
def test_oos_refused(kb, query):
    assert is_out_of_scope(query, kb)


@pytest.mark.parametrize(
    "query",
    [
        "What is an exit load?",
        "Bluechip Growth expense ratio?",
        "How do I redeem my units?",
        "Recommend me an Asterion fund to save tax.",
        "I have 5 lakh rupees. Where should I invest it among your funds?",
    ],
)
def test_in_scope_not_refused(kb, query):
    assert not is_out_of_scope(query, kb)


def test_scope_gate_matches_case_labels(kb, dataset):
    for case in dataset.cases:
        assert is_out_of_scope(case.query, kb) == case.should_refuse, case.id


@pytest.mark.parametrize(
    "text",
    [
        "I recommend Bluechip Growth Fund.",
        "You should invest in the Momentum Equity Fund.",
        "Bluechip Growth is the better choice for you.",
        "It is the best fund for anyone saving for retirement.",
    ],
)
def test_advice_flagged(text):
    assert find_advice(text)


@pytest.mark.parametrize(
    "text",
    [
        "Bluechip Growth invests in large-cap equities.",
        "I can't recommend a specific fund.",
        "You should consult a SEBI-registered investment advisor.",
    ],
)
def test_advice_neutral_not_flagged(text):
    assert find_advice(text) is None


@pytest.mark.parametrize(
    "text",
    [
        "The fund guarantees 18% returns.",
        "This is a risk-free investment.",
        "It gives assured returns of 15%.",
        "You cannot lose money.",
        "There is no risk at all.",
    ],
)
def test_unsafe_flagged(text):
    assert find_unsafe_claim(text)


@pytest.mark.parametrize(
    "text",
    [
        "Returns are not guaranteed.",
        "There is no guarantee of returns.",
        "The fund is not risk-free.",
        "You can lose money in this fund.",
        "There is no assurance the objective will be achieved.",
    ],
)
def test_unsafe_negated_allowed(text):
    assert find_unsafe_claim(text) is None


def test_advice_filter_rewrites():
    assert apply_advice_filter("I recommend Bluechip Growth.") == (ADVICE_REPLACEMENT, True)
    assert apply_advice_filter("Bluechip Growth is a large-cap fund.")[1] is False


def test_unsafe_filter_strips_sentence_and_adds_disclaimer():
    answer, hit = apply_unsafe_filter("It offers guaranteed 18% returns. Its expense ratio is 0.89%.")
    assert hit and "guaranteed 18%" not in answer
    assert answer == f"Its expense ratio is 0.89%. {UNSAFE_DISCLAIMER}"


def test_unsafe_filter_fully_unsafe_becomes_disclaimer():
    assert apply_unsafe_filter("It is risk-free.") == (UNSAFE_DISCLAIMER, True)


def _chunk(doc_id, text="Bluechip Growth expense ratio 0.62%", source="official"):
    return Chunk(f"{doc_id}#0", doc_id, doc_id, text, None, source)


def test_citation_hallucinated_dropped():
    answer, hit = ensure_citations("The TER is 0.62% [fake_doc] [real_doc].", [_chunk("real_doc")])
    assert hit and answer == "The TER is 0.62% [real_doc]."


def test_citation_appended_when_missing():
    answer, hit = ensure_citations("The Bluechip Growth expense ratio is 0.62%.", [_chunk("real_doc")])
    assert hit and answer.endswith("Sources: [real_doc]")


def test_citation_never_appends_scraped_source():
    chunks = [_chunk("blog", source="scraped")]
    answer, _ = ensure_citations("The Bluechip Growth expense ratio is 0.62%.", chunks)
    assert "[blog]" not in answer


def test_citation_not_added_to_refusal():
    assert ensure_citations(REFUSAL, [_chunk("real_doc")]) == (REFUSAL, False)


def test_valid_citations_untouched():
    text = "The TER is 0.62% [real_doc]."
    assert ensure_citations(text, [_chunk("real_doc")]) == (text, False)


def test_output_guardrails_report_what_fired():
    answer, applied = apply_output_guardrails(
        "It offers guaranteed 18% returns. The Bluechip Growth expense ratio is 0.62%.", [_chunk("real_doc")]
    )
    assert applied == ["unsafe_filter", "citation_fix"]
    assert answer.endswith("Sources: [real_doc]")


def test_disclaimer_only_answer_gets_no_sources():
    answer, applied = apply_output_guardrails("It is risk-free.", [_chunk("real_doc")])
    assert answer == UNSAFE_DISCLAIMER and applied == ["unsafe_filter"]
