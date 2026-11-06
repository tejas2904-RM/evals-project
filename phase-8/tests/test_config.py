import pytest

from evalpilot.config import ConfigError, load_dotenv, load_settings


def test_config_loads_toml(settings):
    assert settings.budget_usd == 3.0
    assert settings.default_provider == "offline"
    assert set(settings.providers) == {"openai", "groq", "ollama", "offline"}
    assert settings.max_completion_tokens == 400


def test_models_come_from_env(settings):
    assert settings.bot_model == "gpt-5.4-nano"
    assert settings.judge_model == "gpt-5.4-mini"


def test_model_env_can_be_switched(monkeypatch, root):
    monkeypatch.setenv("EVALPILOT_BOT_MODEL", "llama-3.1-8b-instant")
    assert load_settings(root).bot_model == "llama-3.1-8b-instant"


@pytest.mark.parametrize("var", ["EVALPILOT_BOT_MODEL", "EVALPILOT_JUDGE_MODEL"])
def test_missing_model_env_errors(monkeypatch, tmp_project, var):
    monkeypatch.delenv(var)
    with pytest.raises(ConfigError, match=var):
        load_settings(tmp_project)


def test_only_openai_is_paid(settings):
    assert [name for name, p in settings.providers.items() if p.paid] == ["openai"]


def test_offline_requires_no_key(settings):
    assert settings.api_key("offline") is None


def test_paid_provider_without_key_errors(settings):
    with pytest.raises(ConfigError, match="OPENAI_API_KEY"):
        settings.api_key("openai")


def test_unpaid_provider_without_key_is_none(settings):
    assert settings.api_key("groq") is None


def test_unknown_provider_errors(settings):
    with pytest.raises(ConfigError, match="Unknown provider"):
        settings.provider("anthropic")


def test_ollama_base_url_from_env(monkeypatch, root):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://gpu-box:11434/v1")
    assert load_settings(root).provider("ollama").base_url == "http://gpu-box:11434/v1"


def test_dotenv_loads_without_overriding(monkeypatch, tmp_path):
    env = tmp_path / ".env"
    env.write_text('# comment\nOPENAI_API_KEY="sk-test"\nEVALPILOT_BOT_MODEL=other\n', encoding="utf-8")
    load_dotenv(env)
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-test"
    assert os.environ["EVALPILOT_BOT_MODEL"] == "gpt-5.4-nano"
    monkeypatch.delenv("OPENAI_API_KEY")


def test_paths_resolve_under_root(settings, root):
    assert settings.cases_path == root / "data" / "cases.jsonl"
    assert settings.corpus_dir == root / "data" / "corpus"
    assert settings.judge_prompts_path.is_file()


def test_pricing_table_present_for_both_models(settings):
    assert {"gpt-5.4-nano", "gpt-5.4-mini"} <= set(settings.pricing)


def test_gitignore_excludes_secrets_and_cache(root):
    ignored = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in ignored
    assert ".cache/" in ignored
    assert (root / ".env.example").is_file()
