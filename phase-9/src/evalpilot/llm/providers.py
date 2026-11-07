"""Transports: one OpenAI-compatible SDK client per base URL, plus a keyless offline responder."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from evalpilot.config import ConfigError, ProviderConfig, Settings
from evalpilot.llm.types import RawResponse, Usage

Transport = Callable[[dict[str, Any]], RawResponse]

OFFLINE_JUDGE_REPLY = json.dumps({"pass": True, "reason": "offline stub verdict"})


def openai_transport(base_url: str | None, api_key: str, timeout_s: float = 60.0) -> Transport:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key=api_key, max_retries=0, timeout=timeout_s)

    def send(request: dict[str, Any]) -> RawResponse:
        completion = client.chat.completions.create(**request)
        return RawResponse(
            content=completion.choices[0].message.content or "",
            model=completion.model,
            usage=Usage.from_openai(completion.usage),
        )

    return send


def transport_for(settings: Settings, provider: ProviderConfig) -> Transport:
    if provider.name == "offline":
        raise ConfigError("offline provider has no network transport")
    if provider.key_env:
        key = settings.api_key(provider.name)
        if not key:
            raise ConfigError(f"{provider.key_env} is not set. Add it to .env or pick another provider.")
    else:
        key = provider.name  # Ollama ignores the key but the SDK requires a non-empty one.
    return openai_transport(provider.base_url, key)


class OfflineResponder:
    """Deterministic, keyless answers. Fixture keys are looked up first; otherwise a stub reply."""

    def __init__(self, fixtures_path: Path | None = None, *extra_paths: Path) -> None:
        self.fixtures: dict[str, str] = {}
        for path in (fixtures_path, *extra_paths):
            if path and path.is_file():
                with path.open(encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            row = json.loads(line)
                            self.fixtures[row["key"]] = row["content"]

    def respond(self, request: dict[str, Any], offline_key: str | None) -> RawResponse:
        if offline_key and offline_key in self.fixtures:
            content = self.fixtures[offline_key]
        elif "response_format" in request:
            content = OFFLINE_JUDGE_REPLY
        else:
            last_user = next((m["content"] for m in reversed(request["messages"]) if m["role"] == "user"), "")
            content = f"[offline] {last_user[:120]}"
        return RawResponse(content=content, model=f"offline/{request['model']}")
