from conftest import MESSAGES, FakeTransport

from evalpilot.llm import LlmClient
from evalpilot.llm.cache import ResponseCache, cache_key
from evalpilot.llm.types import RawResponse


def test_cache_hit_skips_network_and_spend(paid_client, fake_transport):
    first = paid_client.chat(MESSAGES)
    spent = paid_client.ledger.total()
    second = paid_client.chat(MESSAGES)

    assert len(fake_transport.requests) == 1
    assert not first.cached and second.cached
    assert second.content == first.content
    assert second.cost_usd == 0.0
    assert paid_client.ledger.total() == spent
    assert len(paid_client.ledger.entries()) == 1


def test_cache_survives_new_client(settings, paid_client, fake_transport):
    paid_client.chat(MESSAGES)
    fresh_transport = FakeTransport()
    fresh = LlmClient(settings, "openai", transport=fresh_transport)
    assert fresh.chat(MESSAGES).cached
    assert fresh_transport.requests == []


def test_cache_key_changes_with_prompt():
    a = cache_key("openai", {"model": "m", "messages": [{"role": "user", "content": "a"}]})
    b = cache_key("openai", {"model": "m", "messages": [{"role": "user", "content": "b"}]})
    assert a != b


def test_cache_key_changes_with_model_and_provider():
    req = {"model": "m1", "messages": []}
    assert cache_key("openai", req) != cache_key("openai", {**req, "model": "m2"})
    assert cache_key("openai", req) != cache_key("groq", req)


def test_cache_key_is_order_independent():
    assert cache_key("p", {"a": 1, "b": 2}) == cache_key("p", {"b": 2, "a": 1})


def test_corrupt_cache_entry_is_a_miss(tmp_path):
    cache = ResponseCache(tmp_path)
    key = "ab" + "0" * 62
    cache.put(key, RawResponse(content="x", model="m"))
    (tmp_path / "ab" / f"{key}.json").write_text("{broken", encoding="utf-8")
    assert cache.get(key) is None


def test_purpose_selects_model_and_separate_cache(paid_client, fake_transport):
    paid_client.chat(MESSAGES, purpose="bot")
    paid_client.chat(MESSAGES, purpose="judge")
    assert [r["model"] for r in fake_transport.requests] == ["gpt-5.4-nano", "gpt-5.4-mini"]
