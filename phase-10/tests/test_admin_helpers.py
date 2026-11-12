"""Unit tests for admin helpers, card draft and the view-model functions the web screens call."""

import pytest

from evalpilot.api.admin import AdminInputError, parse_target, write_inputs
from evalpilot.api.views import critical_graders, guardrail_state
from evalpilot.audit.card_draft import draft_card
from evalpilot.audit.files import SourceFile


def test_parse_target_rewrites_placeholders_and_paths():
    t = parse_target("https://bot.example/chat", '{"q": "$QUESTION", "s": "$SESSION"}', "data.items[0].text")
    assert t.url == "https://bot.example/chat"
    assert "{message}" in t.body and "{session_id}" in t.body and "$QUESTION" not in t.body
    assert t.answer_path == "$.data.items[0].text"
    assert "$.data.items[0].text" in t.adapter_toml()


def test_parse_target_strips_jsonpath_prefix():
    t = parse_target("http://127.0.0.1:9/", '{"message":"$QUESTION"}', "$.reply")
    assert t.answer_path == "$.reply"


@pytest.mark.parametrize("url,body,path,match", [
    ("ftp://x", '{"message":"$QUESTION"}', "reply", "http"),
    ("https://x", "{}", "reply", r"\$QUESTION"),
    ("https://x", '{"message":"$QUESTION"}', "foo;bar", "answer path"),
    ("https://x", '{"message": $QUESTION}', "reply", "valid JSON"),
])
def test_parse_target_rejects_bad_inputs(url, body, path, match):
    with pytest.raises(AdminInputError, match=match):
        parse_target(url, body, path)


def test_write_inputs_persists_adapter_and_card(tmp_path):
    t = parse_target("https://bot.example/chat", '{"message":"$QUESTION"}', "reply")
    written = write_inputs(tmp_path / "in", t, '{"name":"GymCoach"}')
    assert written["adapter"].read_text(encoding="utf-8").startswith("[request]")
    assert '"GymCoach"' in written["system_card"].read_text(encoding="utf-8")


def test_draft_card_from_source_text():
    files = [
        SourceFile("README.md", "# GymCoach bot\n"),
        SourceFile("tools.py", "@tool\ndef book_session(slot):\n    pass\n\ndef send_email():\n    httpx.post('https://x')\n"),
        SourceFile("bot.py", 'model = "gpt-5.4-mini"\nhtml.escape(answer)\n'),
    ]
    out = draft_card(files)
    assert out["card"]["name"] == "GymCoach bot" and out["files_read"] == 3
    assert any(m["name"] == "gpt-5.4-mini" for m in out["card"]["models"])
    assert any(t["name"] == "book_session" for t in out["card"]["tools"])
    send = next(t for t in out["card"]["tools"] if t["name"] == "send_email")
    assert send["side_effects"] == "external"
    assert "output_encoding" in out["card"]["guardrails_declared"]


def test_guardrail_state_mapping():
    assert guardrail_state({"status": "verified"}) == "present"
    assert guardrail_state({"status": "declared"}) == "weak"
    assert guardrail_state({"status": "failed", "passed_checks": ["a"]}) == "weak"
    assert guardrail_state({"status": "failed", "passed_checks": []}) == "missing"
    assert guardrail_state({"status": "n/a"}) == "n/a"
    assert guardrail_state({"status": "absent"}) == "missing"


def test_critical_graders_are_the_near_perfect_gate(settings):
    assert critical_graders(settings) == ["advice", "unsafe_claim"]
