from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_prompt_tokens: int = 0
    reasoning_tokens: int = 0

    @classmethod
    def from_openai(cls, usage: Any) -> Usage:
        if usage is None:
            return cls()
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        completion_details = getattr(usage, "completion_tokens_details", None)
        return cls(
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            cached_prompt_tokens=getattr(prompt_details, "cached_tokens", 0) or 0,
            reasoning_tokens=getattr(completion_details, "reasoning_tokens", 0) or 0,
        )


class RawResponse(BaseModel):
    """What a transport returns and what the disk cache stores."""

    content: str
    model: str
    usage: Usage = Field(default_factory=Usage)


class LlmResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: str
    model: str
    provider: str
    usage: Usage
    cost_usd: float = 0.0
    cached: bool = False


class LedgerEntry(BaseModel):
    ts: str
    run_id: str
    provider: str
    model: str
    purpose: str
    prompt_tokens: int
    cached_prompt_tokens: int
    completion_tokens: int
    cost_usd: float
