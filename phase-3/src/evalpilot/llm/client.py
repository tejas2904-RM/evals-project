"""LlmClient: offline -> cache -> budget guard -> network (with retry) -> ledger -> cache write."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Literal

from evalpilot.config import Settings
from evalpilot.llm.budget import BudgetGuard, Ledger, cost_usd, require_pricing
from evalpilot.llm.cache import ResponseCache, cache_key
from evalpilot.llm.providers import OfflineResponder, Transport, transport_for
from evalpilot.llm.retry import call_with_retry
from evalpilot.llm.types import LlmResponse

REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
Purpose = Literal["bot", "judge", "smoke"]


def is_reasoning_model(model: str) -> bool:
    return model.startswith(REASONING_MODEL_PREFIXES)


def build_request(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_completion_tokens: int,
    reasoning_effort: str,
    json_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Chat Completions payload. GPT-5.x reasoning models reject `temperature`, so it is never sent."""
    request: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_completion_tokens,
    }
    if is_reasoning_model(model):
        request["reasoning_effort"] = reasoning_effort
    if json_schema is not None:
        request["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": json_schema.get("title", "response"), "schema": json_schema, "strict": True},
        }
    return request


class LlmClient:
    def __init__(
        self,
        settings: Settings,
        provider_name: str,
        *,
        transport: Transport | None = None,
        ledger: Ledger | None = None,
        cache: ResponseCache | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.settings = settings
        self.provider = settings.provider(provider_name)
        self.ledger = ledger or Ledger(settings.ledger_path)
        self.cache = cache or ResponseCache(settings.llm_cache_dir)
        self.guard = BudgetGuard(settings.budget_usd, self.ledger)
        self._sleep = sleep
        self._offline = OfflineResponder(self.provider.fixtures) if self.provider.name == "offline" else None
        self._transport = transport
        if self._offline is None and self._transport is None:
            self._transport = transport_for(settings, self.provider)
        self.calls = 0
        self.cache_hits = 0
        self.session_cost_usd = 0.0

    def model_for(self, purpose: Purpose) -> str:
        return self.settings.judge_model if purpose == "judge" else self.settings.bot_model

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        purpose: Purpose = "bot",
        model: str | None = None,
        run_id: str = "",
        json_schema: dict[str, Any] | None = None,
        offline_key: str | None = None,
    ) -> LlmResponse:
        model = model or self.model_for(purpose)
        request = build_request(
            model,
            messages,
            max_completion_tokens=self.settings.max_completion_tokens,
            reasoning_effort=self.settings.reasoning_effort,
            json_schema=json_schema,
        )
        self.calls += 1

        if self._offline is not None:
            raw = self._offline.respond(request, offline_key)
            return LlmResponse(content=raw.content, model=raw.model, provider="offline", usage=raw.usage)

        key = cache_key(self.provider.name, request)
        if (hit := self.cache.get(key)) is not None:
            self.cache_hits += 1
            return LlmResponse(content=hit.content, model=hit.model, provider=self.provider.name, usage=hit.usage, cached=True)

        prices = None
        if self.provider.paid:
            prices = require_pricing(self.settings.pricing, model)
            self.guard.check()

        assert self._transport is not None
        raw = call_with_retry(lambda: self._transport(request), self.settings.retry, sleep=self._sleep)

        cost = 0.0
        if prices is not None:
            cost = cost_usd(prices, raw.usage)
            self.ledger.append(
                run_id=run_id, provider=self.provider.name, model=model, purpose=purpose, usage=raw.usage, cost=cost
            )
            self.session_cost_usd += cost
        self.cache.put(key, raw)
        return LlmResponse(content=raw.content, model=raw.model, provider=self.provider.name, usage=raw.usage, cost_usd=cost)
