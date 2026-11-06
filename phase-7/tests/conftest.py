import os
from pathlib import Path

import httpx
import openai
import pytest

from evalpilot.llm.types import RawResponse, Usage

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LIVE = os.getenv("EVALPILOT_LIVE") == "1"


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch, tmp_path):
    """Deterministic env: models set, no real keys, cache + ledger in a temp dir."""
    for var in ("GROQ_API_KEY", "EVALPILOT_ROOT", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    if not LIVE:
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        # A real key in the developer's .env must not leak into offline tests.
        monkeypatch.setattr("evalpilot.config.load_dotenv", lambda _path: None)
    monkeypatch.setenv("EVALPILOT_BOT_MODEL", "gpt-5.4-nano")
    monkeypatch.setenv("EVALPILOT_JUDGE_MODEL", "gpt-5.4-mini")
    monkeypatch.setenv("EVALPILOT_CACHE_DIR", str(tmp_path / ".cache"))
    monkeypatch.setenv("EVALPILOT_RUNS_DIR", str(tmp_path / "runs"))


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any attempt to build a real SDK transport outside live tests is a test failure."""
    if LIVE:
        return

    def blocked(*_args, **_kwargs):
        raise AssertionError("network transport created in an offline test")

    monkeypatch.setattr("evalpilot.llm.providers.openai_transport", blocked)


@pytest.fixture
def root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def settings(root):
    from evalpilot.config import load_settings

    return load_settings(root)


@pytest.fixture
def dataset(settings):
    from evalpilot.data import load_dataset

    return load_dataset(settings.cases_path, settings.corpus_dir)


@pytest.fixture
def kb(dataset):
    from evalpilot.bot.corpus import KnowledgeBase

    return KnowledgeBase(dataset.docs)


@pytest.fixture
def naive(kb):
    from evalpilot.bot.retriever import NaiveRetriever

    return NaiveRetriever(kb, top_k=4)


@pytest.fixture
def entity_aware(kb):
    from evalpilot.bot.retriever import EntityAwareRetriever

    return EntityAwareRetriever(kb, top_k=4)


@pytest.fixture
def cases_by_id(dataset):
    return {c.id: c for c in dataset.cases}


@pytest.fixture
def audit_cfg(settings):
    return settings.audit


@pytest.fixture
def examples(root) -> Path:
    return root / "examples"


@pytest.fixture
def tmp_project(tmp_path, root) -> Path:
    """A copy of evals.toml in an empty dir, for config edge cases."""
    project = tmp_path / "project"
    project.mkdir()
    (project / "evals.toml").write_text((root / "evals.toml").read_text(encoding="utf-8"), encoding="utf-8")
    return project


def http_error(cls, status: int, headers: dict[str, str] | None = None):
    request = httpx.Request("POST", "https://api.example.test/v1/chat/completions")
    response = httpx.Response(status, request=request, headers=headers or {})
    return cls(f"HTTP {status}", response=response, body=None)


def connection_error():
    return openai.APIConnectionError(request=httpx.Request("POST", "https://api.example.test"))


class FakeTransport:
    """Records requests; replays scripted exceptions, then returns a fixed reply."""

    def __init__(self, content="ok", usage=None, errors=()):
        self.content = content
        self.usage = usage or Usage(prompt_tokens=1000, completion_tokens=200)
        self.errors = list(errors)
        self.requests: list[dict] = []

    def __call__(self, request):
        self.requests.append(request)
        if self.errors:
            raise self.errors.pop(0)
        return RawResponse(content=self.content, model=request["model"], usage=self.usage)


@pytest.fixture
def fake_transport():
    return FakeTransport()


@pytest.fixture
def paid_client(settings, fake_transport):
    from evalpilot.llm import LlmClient

    return LlmClient(settings, "openai", transport=fake_transport, sleep=lambda _s: None)


MESSAGES = [{"role": "user", "content": "What is the exit load on Bluechip Growth?"}]
