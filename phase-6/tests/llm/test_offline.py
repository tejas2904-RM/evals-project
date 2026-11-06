import json
import os

import pytest
from conftest import MESSAGES

from evalpilot.config import ConfigError
from evalpilot.llm import LlmClient
from evalpilot.llm.providers import OfflineResponder


def test_offline_works_without_any_key(settings):
    assert "OPENAI_API_KEY" not in os.environ
    client = LlmClient(settings, "offline")
    response = client.chat(MESSAGES)
    assert response.provider == "offline"
    assert response.cost_usd == 0.0
    assert client.ledger.entries() == []


def test_offline_never_reads_the_key(settings, monkeypatch):
    reads: list[str] = []
    real_get = os.environ.get

    def spy(key, default=None):
        reads.append(key)
        return real_get(key, default)

    monkeypatch.setattr(os.environ, "get", spy)
    LlmClient(settings, "offline").chat(MESSAGES)
    assert "OPENAI_API_KEY" not in reads


def test_offline_fixture_lookup(settings):
    assert LlmClient(settings, "offline").chat(MESSAGES, offline_key="smoke").content == "pong"


def test_offline_json_mode_returns_binary_verdict(settings):
    schema = {"title": "verdict", "type": "object"}
    content = LlmClient(settings, "offline").chat(MESSAGES, purpose="judge", json_schema=schema).content
    assert json.loads(content) == {"pass": True, "reason": "offline stub verdict"}


def test_offline_is_deterministic(settings):
    client = LlmClient(settings, "offline")
    assert client.chat(MESSAGES).content == client.chat(MESSAGES).content


def test_offline_does_not_write_cache(settings):
    LlmClient(settings, "offline").chat(MESSAGES)
    assert not settings.llm_cache_dir.exists()


def test_missing_fixture_file_is_fine(tmp_path):
    responder = OfflineResponder(tmp_path / "nope.jsonl")
    assert responder.fixtures == {}


def test_openai_without_key_fails_fast(settings):
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        LlmClient(settings, "openai")


def test_groq_without_key_fails_fast(settings):
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        LlmClient(settings, "groq")


def test_ollama_needs_no_key(settings, monkeypatch):
    seen = {}

    def fake_transport(base_url, api_key, timeout_s=60.0):
        seen.update(base_url=base_url, api_key=api_key)
        return lambda request: None

    monkeypatch.setattr("evalpilot.llm.providers.openai_transport", fake_transport)
    LlmClient(settings, "ollama")
    assert seen == {"base_url": "http://localhost:11434/v1", "api_key": "ollama"}


def test_one_client_for_all_providers(settings, monkeypatch):
    urls = []
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "evalpilot.llm.providers.openai_transport",
        lambda base_url, api_key, timeout_s=60.0: urls.append(base_url) or (lambda r: None),
    )
    for name in ("openai", "groq", "ollama"):
        LlmClient(settings, name)
    assert urls == ["https://api.openai.com/v1", "https://api.groq.com/openai/v1", "http://localhost:11434/v1"]
