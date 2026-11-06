"""One real gpt-5.4-nano call (~$0.00002). Run manually: EVALPILOT_LIVE=1 pytest -m live"""

import os

import pytest

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("EVALPILOT_LIVE") != "1" or not os.getenv("OPENAI_API_KEY"),
        reason="set EVALPILOT_LIVE=1 and OPENAI_API_KEY to run the paid smoke test",
    ),
]


def test_openai_smoke_call_is_billed_and_cached(monkeypatch, root):
    monkeypatch.delenv("EVALPILOT_CACHE_DIR")  # bill the real project ledger
    from evalpilot.config import load_settings
    from evalpilot.llm import LlmClient

    settings = load_settings(root)
    client = LlmClient(settings, "openai")
    before = client.ledger.total()
    messages = [{"role": "user", "content": "Reply with exactly one word: pong (live test)"}]

    first = client.chat(messages, run_id="live-test")
    assert first.content.strip()
    assert first.cached or client.ledger.total() > before

    second = client.chat(messages, run_id="live-test")
    assert second.cached and second.cost_usd == 0.0
