"""System card: what the owner declares about their LLM system (Docs/Audit.md section 2.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class CardError(ValueError):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ModelSpec(_Strict):
    provider: str = ""
    name: str
    pinned_version: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None


class PromptPolicy(_Strict):
    contains_secrets: bool = False
    disclosure_allowed: bool = False


class DataSource(_Strict):
    name: str
    type: Literal["official", "scraped", "user"]
    ingestion: str = ""
    tenant_isolation: bool = False


class Tool(_Strict):
    name: str
    side_effects: Literal["none", "read", "write", "external"]
    requires_confirmation: bool = False
    scopes: list[str] = Field(default_factory=list)


class RateLimits(_Strict):
    per_user_rpm: int | None = None
    max_input_chars: int | None = None
    max_output_tokens: int | None = None


class LoggingPolicy(_Strict):
    logs_prompts: bool = False
    pii_redaction: bool = False
    retention_days: int | None = None


class SystemCard(BaseModel):
    """Unknown top-level fields are kept (and flagged by config review), not rejected."""

    model_config = ConfigDict(extra="allow")

    name: str
    version: str = ""
    owner: str = ""
    purpose: str = ""
    intended_users: list[str] | str = Field(default_factory=list)
    out_of_scope_topics: list[str] = Field(default_factory=list)
    models: list[ModelSpec] = Field(default_factory=list)
    system_prompt_policy: PromptPolicy = Field(default_factory=PromptPolicy)
    data_sources: list[DataSource] = Field(default_factory=list)
    tools: list[Tool] = Field(default_factory=list)
    guardrails_declared: list[str] = Field(default_factory=list)
    rate_limits: RateLimits = Field(default_factory=RateLimits)
    logging: LoggingPolicy = Field(default_factory=LoggingPolicy)
    secrets_management: Literal["env", "vault", "inline"] = "env"
    human_in_the_loop: list[str] = Field(default_factory=list)
    # Tokens the owner planted for the audit (hidden prompt, documents, other tenant, PII).
    canaries: dict[str, str] = Field(default_factory=dict)

    def unknown_fields(self) -> list[str]:
        return sorted(self.model_extra or {})


def load_system_card(path: Path) -> SystemCard:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CardError(f"{path.name}: cannot read system card ({exc})") from exc
    try:
        return SystemCard.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise CardError(f"{path.name}: invalid system card at '{where}': {first['msg']}") from exc
