from evalpilot.bot.corpus import Chunk
from evalpilot.bot.prompts import SYSTEM_V1, build_messages, format_context, system_prompt


def test_v1_prompt_is_naive():
    prompt = system_prompt("v1")
    assert prompt == SYSTEM_V1
    for rule in ("refuse", "recommend", "guarantee", "cite", "square brackets"):
        assert rule not in prompt.lower()


def test_v2_prompt_has_guardrail_rules():
    prompt = system_prompt("v2").lower()
    for rule in ("i can only answer questions", "never recommend", "guarantee", "square brackets", "scraped"):
        assert rule in prompt


def test_v3_prompt_scopes_entity():
    assert "Asterion Bluechip Value Fund" in system_prompt("v3", ["Asterion Bluechip Value Fund"])
    assert system_prompt("v3", []) == system_prompt("v2")


def test_context_labels_doc_ids():
    chunk = Chunk("d#0", "d", "Title", "Body", None, "official")
    assert format_context([chunk]) == "[d] Title\nBody"
    assert "no relevant documents" in format_context([])


def test_messages_shape():
    messages = build_messages("v2", "What is NAV?", [])
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[1]["content"].endswith("Question: What is NAV?")
