"""Load evals.toml and .env into a single Settings object."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILE = "evals.toml"
ENV_FILE = ".env"


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    paid: bool
    base_url: str | None = None
    key_env: str | None = None


@dataclass(frozen=True)
class Settings:
    root: Path
    budget_usd: float
    default_provider: str
    bot_model: str
    judge_model: str
    max_completion_tokens: int
    reasoning_effort: str
    providers: dict[str, ProviderConfig]
    pricing: dict[str, dict[str, float]]
    data_dir: Path
    runs_dir: Path
    cache_dir: Path

    @property
    def cases_path(self) -> Path:
        return self.data_dir / "cases.jsonl"

    @property
    def corpus_dir(self) -> Path:
        return self.data_dir / "corpus"

    @property
    def judge_prompts_path(self) -> Path:
        return self.data_dir / "judge_prompts.md"

    @property
    def labels_path(self) -> Path:
        return self.data_dir / "labels.jsonl"

    def provider(self, name: str) -> ProviderConfig:
        try:
            return self.providers[name]
        except KeyError:
            raise ConfigError(f"Unknown provider '{name}'. Known: {', '.join(sorted(self.providers))}") from None

    def api_key(self, provider_name: str) -> str | None:
        """Return the provider's key. Offline (no key_env) never touches the environment."""
        provider = self.provider(provider_name)
        if provider.key_env is None:
            return None
        key = os.environ.get(provider.key_env, "").strip()
        if provider.paid and not key:
            raise ConfigError(f"{provider.key_env} is not set. Add it to .env (gitignored) or use --provider offline.")
        return key or None


def find_root(start: Path | None = None) -> Path:
    if env_root := os.environ.get("EVALPILOT_ROOT"):
        return Path(env_root).resolve()
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / CONFIG_FILE).is_file():
            return candidate
    package_root = Path(__file__).resolve().parents[2]
    if (package_root / CONFIG_FILE).is_file():
        return package_root
    raise ConfigError(f"Could not find {CONFIG_FILE} from {here}")


def load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE loader. Existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def _require_env(var: str) -> str:
    value = os.environ.get(var, "").strip()
    if not value:
        raise ConfigError(f"Environment variable {var} is not set. Copy .env.example to .env or export it.")
    return value


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    section = raw.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"{CONFIG_FILE}: missing [{name}] section")
    return section


def _parse_providers(raw: dict[str, Any]) -> dict[str, ProviderConfig]:
    providers: dict[str, ProviderConfig] = {}
    for name, cfg in _section(raw, "providers").items():
        base_url = cfg.get("base_url")
        if env_var := cfg.get("base_url_env"):
            base_url = os.environ.get(env_var, "").strip() or base_url
        providers[name] = ProviderConfig(
            name=name,
            paid=bool(cfg.get("paid", False)),
            base_url=base_url,
            key_env=cfg.get("key_env"),
        )
    if "offline" not in providers:
        raise ConfigError(f"{CONFIG_FILE}: [providers.offline] is required")
    if providers["offline"].paid or providers["offline"].key_env:
        raise ConfigError(f"{CONFIG_FILE}: offline provider must be unpaid and keyless")
    return providers


def load_settings(root: Path | None = None) -> Settings:
    root = (root or find_root()).resolve()
    config_path = root / CONFIG_FILE
    if not config_path.is_file():
        raise ConfigError(f"{config_path} not found")
    load_dotenv(root / ENV_FILE)

    with config_path.open("rb") as fh:
        raw = tomllib.load(fh)

    project = _section(raw, "project")
    models = _section(raw, "models")
    paths = raw.get("paths", {})
    providers = _parse_providers(raw)

    budget = float(project.get("budget_usd", 0))
    if budget <= 0:
        raise ConfigError(f"{CONFIG_FILE}: project.budget_usd must be > 0")
    default_provider = project.get("default_provider", "offline")
    if default_provider not in providers:
        raise ConfigError(f"{CONFIG_FILE}: default_provider '{default_provider}' is not a configured provider")

    return Settings(
        root=root,
        budget_usd=budget,
        default_provider=default_provider,
        bot_model=_require_env(models.get("bot_env", "EVALPILOT_BOT_MODEL")),
        judge_model=_require_env(models.get("judge_env", "EVALPILOT_JUDGE_MODEL")),
        max_completion_tokens=int(models.get("max_completion_tokens", 400)),
        reasoning_effort=str(models.get("reasoning_effort", "minimal")),
        providers=providers,
        pricing={k: {kk: float(vv) for kk, vv in v.items()} for k, v in raw.get("pricing", {}).items()},
        data_dir=root / paths.get("data_dir", "data"),
        runs_dir=root / paths.get("runs_dir", "runs"),
        cache_dir=root / paths.get("cache_dir", ".cache"),
    )
