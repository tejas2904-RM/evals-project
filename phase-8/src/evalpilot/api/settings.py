"""API settings from the environment. The hosted service is read-only and keyless by default."""

from __future__ import annotations

import os
from dataclasses import dataclass

MODES = ("readonly", "jobs")
PAID_KEY_ENVS = ("OPENAI_API_KEY", "GROQ_API_KEY")
DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


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

    @property
    def jobs_enabled(self) -> bool:
        return self.mode == "jobs"

    @classmethod
    def from_env(cls) -> "ApiSettings":
        mode = os.environ.get("EVALPILOT_API_MODE", "readonly").strip() or "readonly"
        if mode not in MODES:
            raise ApiConfigError(f"EVALPILOT_API_MODE must be one of {MODES}, got {mode!r}")
        origins = tuple(o.strip().rstrip("/") for o in os.environ.get("EVALPILOT_ALLOWED_ORIGINS", "").split(",") if o.strip())
        if "*" in origins:
            raise ApiConfigError("EVALPILOT_ALLOWED_ORIGINS must list origins explicitly, not '*'")
        # Render sets RENDER=true on every service; EVALPILOT_HOSTED=1 forces the same rules elsewhere.
        hosted = os.environ.get("RENDER", "").lower() == "true" or os.environ.get("EVALPILOT_HOSTED") == "1"
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


def assert_keyless(api: ApiSettings) -> None:
    """A hosted API must not be able to spend money: Render's disk is ephemeral, so a ledger there would reset."""
    if not api.hosted:
        return
    present = [name for name in PAID_KEY_ENVS if os.environ.get(name)]
    if present:
        raise ApiConfigError(f"refusing to start: the hosted API must not hold paid keys ({', '.join(present)} set)")
