"""API settings from the environment.

Phase 8–9: hosted is read-only and keyless. Phase 10: hosted `jobs` may hold OPENAI_API_KEY on Render
(dashboard Secret). Hosted `readonly` still refuses a paid key. Admin mode is still local-only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

MODES = ("readonly", "jobs")
PAID_KEY_ENVS = ("OPENAI_API_KEY", "GROQ_API_KEY")
DEFAULT_ORIGINS = ("http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:5173", "http://127.0.0.1:5173")
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


class ApiConfigError(RuntimeError):
    pass


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ApiConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if value < 1:
        raise ApiConfigError(f"{name} must be >= 1, got {value}")
    return value


def is_hosted() -> bool:
    # Render sets RENDER=true on every service; EVALPILOT_HOSTED=1 forces the same rules elsewhere.
    return os.environ.get("RENDER", "").lower() == "true" or os.environ.get("EVALPILOT_HOSTED") == "1"


@dataclass(frozen=True)
class ApiSettings:
    mode: str = "readonly"
    allowed_origins: tuple[str, ...] = DEFAULT_ORIGINS
    allowed_origin_regex: str | None = None
    hosted: bool = False
    max_upload_bytes: int = 5 * 1024 * 1024
    post_per_minute: int = 6
    max_queued_jobs: int = 3
    max_kept_jobs: int = 50
    trust_forwarded_for: bool = False
    # Admin mode: the owner's machine only (`evalpilot serve --admin`). Never set from the environment.
    admin_token: str | None = None
    admin_provider: str = "offline"

    @property
    def admin(self) -> bool:
        return self.admin_token is not None

    @property
    def jobs_enabled(self) -> bool:
        return self.mode == "jobs" or self.admin

    @classmethod
    def from_env(cls) -> "ApiSettings":
        mode = os.environ.get("EVALPILOT_API_MODE", "readonly").strip() or "readonly"
        if mode not in MODES:
            raise ApiConfigError(f"EVALPILOT_API_MODE must be one of {MODES}, got {mode!r}")
        origins = tuple(o.strip().rstrip("/") for o in os.environ.get("EVALPILOT_ALLOWED_ORIGINS", "").split(",") if o.strip())
        if "*" in origins:
            raise ApiConfigError("EVALPILOT_ALLOWED_ORIGINS must list origins explicitly, not '*'")
        hosted = is_hosted()
        return cls(
            mode=mode,
            allowed_origins=origins or DEFAULT_ORIGINS,
            allowed_origin_regex=os.environ.get("EVALPILOT_ALLOWED_ORIGIN_REGEX") or None,
            hosted=hosted,
            max_upload_bytes=_int("EVALPILOT_MAX_UPLOAD_MB", 5) * 1024 * 1024,
            post_per_minute=_int("EVALPILOT_POST_PER_MINUTE", 6),
            max_queued_jobs=_int("EVALPILOT_MAX_QUEUED_JOBS", 3),
            trust_forwarded_for=hosted,
        )


def paid_keys_present() -> list[str]:
    return [name for name in PAID_KEY_ENVS if os.environ.get(name)]


def jobs_provider(api: ApiSettings) -> str:
    """OpenAI when a hosted jobs service has a key; otherwise offline. Admin uses admin_provider."""
    if api.admin:
        return api.admin_provider
    if api.jobs_enabled and os.environ.get("OPENAI_API_KEY"):
        return "openai"
    return "offline"


def assert_keyless(api: ApiSettings) -> None:
    """Hosted admin is never allowed. Hosted readonly must stay keyless. Hosted jobs may hold a Render Secret key."""
    if not api.hosted:
        return
    if api.admin:
        raise ApiConfigError("refusing to start: admin mode is for the owner's machine, never a hosted service")
    present = paid_keys_present()
    if present and api.mode != "jobs":
        raise ApiConfigError(f"refusing to start: the hosted API must not hold paid keys ({', '.join(present)} set)")


def assert_admin_host(host: str) -> None:
    if is_hosted():
        raise ApiConfigError("refusing to start: admin mode is for the owner's machine, never a hosted service")
    if host not in LOOPBACK_HOSTS:
        raise ApiConfigError(f"admin mode binds to loopback only (127.0.0.1), not {host!r}")
