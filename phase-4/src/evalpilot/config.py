"""Load evals.toml and .env into a single Settings object."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv as _load_dotenv

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
    fixtures: Path | None = None
    extra_fixtures: tuple[Path, ...] = ()


@dataclass(frozen=True)
class RetryConfig:
    max_attempts: int = 5
    base_delay_s: float = 1.0
    max_delay_s: float = 30.0


@dataclass(frozen=True)
class AuditConfig:
    max_probes: int = 60
    probe_rate_per_s: float = 2.0
    request_timeout_s: float = 20.0
    require_authorization: bool = True
    ai_review: bool = True
    ai_review_max_files: int = 15
    ai_review_max_input_tokens: int = 60_000
    ai_review_max_completion_tokens: int = 1500
    max_repo_mb: int = 50
    max_files: int = 5000
    max_file_kb: int = 1024
    gitleaks_bin: str = "gitleaks"
    severity_critical: int = 20
    severity_high: int = 12
    severity_medium: int = 6
    block_on_critical: bool = True
    max_open_high: int = 0
    ai_only_max_level: str = "medium"


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
    retry: RetryConfig
    top_k: int
    data_dir: Path
    runs_dir: Path
    cache_dir: Path
    audit: AuditConfig = field(default_factory=AuditConfig)

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

    @property
    def llm_cache_dir(self) -> Path:
        return self.cache_dir / "llm"

    @property
    def ledger_path(self) -> Path:
        return self.cache_dir / "spend.jsonl"

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
    """Load .env without overriding variables already set in the environment."""
    if path.is_file():
        _load_dotenv(path, override=False)


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


def _parse_providers(raw: dict[str, Any], root: Path) -> dict[str, ProviderConfig]:
    providers: dict[str, ProviderConfig] = {}
    for name, cfg in _section(raw, "providers").items():
        base_url = cfg.get("base_url")
        if env_var := cfg.get("base_url_env"):
            base_url = os.environ.get(env_var, "").strip() or base_url
        fixtures = cfg.get("fixtures") or []
        fixture_paths = [root / p for p in ([fixtures] if isinstance(fixtures, str) else fixtures)]
        providers[name] = ProviderConfig(
            name=name,
            paid=bool(cfg.get("paid", False)),
            base_url=base_url,
            key_env=cfg.get("key_env"),
            fixtures=fixture_paths[0] if fixture_paths else None,
            extra_fixtures=tuple(fixture_paths[1:]),
        )
    if "offline" not in providers:
        raise ConfigError(f"{CONFIG_FILE}: [providers.offline] is required")
    if providers["offline"].paid or providers["offline"].key_env:
        raise ConfigError(f"{CONFIG_FILE}: offline provider must be unpaid and keyless")
    return providers


def _parse_retry(raw: dict[str, Any]) -> RetryConfig:
    cfg = raw.get("retry", {})
    retry = RetryConfig(
        max_attempts=int(cfg.get("max_attempts", 5)),
        base_delay_s=float(cfg.get("base_delay_s", 1.0)),
        max_delay_s=float(cfg.get("max_delay_s", 30.0)),
    )
    if retry.max_attempts < 1:
        raise ConfigError(f"{CONFIG_FILE}: retry.max_attempts must be >= 1")
    return retry


def _parse_audit(raw: dict[str, Any]) -> AuditConfig:
    cfg = dict(raw.get("audit", {}))
    severity = cfg.pop("severity", {})
    verdict = cfg.pop("verdict", {})
    known = set(AuditConfig.__dataclass_fields__)
    flat = {**cfg, **{f"severity_{k}": v for k, v in severity.items()}, **verdict}
    if unknown := sorted(set(flat) - known):
        raise ConfigError(f"{CONFIG_FILE}: unknown [audit] key(s) {unknown}")
    audit = AuditConfig(**flat)
    if not audit.severity_critical > audit.severity_high > audit.severity_medium > 0:
        raise ConfigError(f"{CONFIG_FILE}: [audit.severity] needs critical > high > medium > 0")
    if audit.ai_only_max_level not in ("critical", "high", "medium", "low"):
        raise ConfigError(f"{CONFIG_FILE}: [audit.verdict] ai_only_max_level must be critical, high, medium or low")
    if audit.max_probes < 1 or audit.probe_rate_per_s <= 0:
        raise ConfigError(f"{CONFIG_FILE}: [audit] max_probes and probe_rate_per_s must be positive")
    return audit


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
    providers = _parse_providers(raw, root)

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
        reasoning_effort=str(models.get("reasoning_effort", "none")),
        providers=providers,
        pricing={k: {kk: float(vv) for kk, vv in v.items()} for k, v in raw.get("pricing", {}).items()},
        retry=_parse_retry(raw),
        top_k=int(raw.get("bot", {}).get("top_k", 4)),
        data_dir=root / paths.get("data_dir", "data"),
        runs_dir=Path(os.environ["EVALPILOT_RUNS_DIR"]).resolve()
        if os.environ.get("EVALPILOT_RUNS_DIR")
        else root / paths.get("runs_dir", "runs"),
        cache_dir=Path(os.environ["EVALPILOT_CACHE_DIR"]).resolve()
        if os.environ.get("EVALPILOT_CACHE_DIR")
        else root / paths.get("cache_dir", ".cache"),
        audit=_parse_audit(raw),
    )
