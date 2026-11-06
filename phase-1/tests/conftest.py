from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_env(monkeypatch):
    """Deterministic env: models set, no real keys, no stray EVALPILOT_ROOT."""
    for var in ("OPENAI_API_KEY", "GROQ_API_KEY", "EVALPILOT_ROOT", "OLLAMA_BASE_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("EVALPILOT_BOT_MODEL", "gpt-5.4-nano")
    monkeypatch.setenv("EVALPILOT_JUDGE_MODEL", "gpt-5.4-mini")


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
def tmp_project(tmp_path, root) -> Path:
    """A copy of evals.toml in an empty dir, for config edge cases."""
    (tmp_path / "evals.toml").write_text((root / "evals.toml").read_text(encoding="utf-8"), encoding="utf-8")
    return tmp_path
