"""HTTP adapter: how to send one message to a target bot and read its reply (adapter.toml)."""

from __future__ import annotations

import json
import os
import re
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

_PATH_TOKEN_RE = re.compile(r"\.([A-Za-z_][\w\-]*)|\[(\d+)\]")


class AdapterError(ValueError):
    pass


@dataclass(frozen=True)
class AdapterConfig:
    method: str = "POST"
    url_path: str = "/chat"
    body: str = '{"message": "{message}", "session_id": "{session_id}"}'
    headers: dict[str, str] = field(default_factory=lambda: {"Content-Type": "application/json"})
    auth_header_env: str | None = None
    auth_header_name: str = "Authorization"
    answer_path: str = "$.reply"
    citations_path: str | None = None
    context_path: str | None = None
    timeout_s: float | None = None
    rate_per_s: float | None = None
    cases: Path | None = None


def load_adapter(path: Path) -> AdapterConfig:
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AdapterError(f"{path.name}: cannot read adapter ({exc})") from exc
    request, response, limits = raw.get("request", {}), raw.get("response", {}), raw.get("limits", {})
    if "answer_jsonpath" not in response:
        raise AdapterError(f"{path.name}: [response].answer_jsonpath is required")
    method = str(request.get("method", "POST")).upper()
    if method not in ("POST", "PUT", "GET"):
        raise AdapterError(f"{path.name}: unsupported method {method}")
    cases = raw.get("behaviour", {}).get("cases")
    return AdapterConfig(
        method=method,
        url_path=request.get("url_path", "/chat"),
        body=request.get("body", AdapterConfig.body),
        headers=dict(request.get("headers", {"Content-Type": "application/json"})),
        auth_header_env=request.get("auth_header_env"),
        auth_header_name=request.get("auth_header_name", "Authorization"),
        answer_path=response["answer_jsonpath"],
        citations_path=response.get("citations_jsonpath"),
        context_path=response.get("context_jsonpath"),
        timeout_s=limits.get("timeout_s"),
        rate_per_s=limits.get("rate_per_s"),
        cases=(path.parent / cases).resolve() if cases else None,
    )


def json_path(data: Any, path: str | None) -> Any:
    """Tiny JSONPath subset: `$`, `$.a.b`, `$.a[0].b`."""
    if not path:
        return None
    if not path.startswith("$"):
        raise AdapterError(f"JSONPath must start with '$': {path}")
    current = data
    for key, index in _PATH_TOKEN_RE.findall(path[1:]):
        if key:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        else:
            i = int(index)
            if not isinstance(current, list) or i >= len(current):
                return None
            current = current[i]
    return current


def render_body(template: str, message: str, session_id: str) -> str:
    escaped = json.dumps(message)[1:-1]
    return template.replace("{message}", escaped).replace("{session_id}", session_id)


@dataclass
class AdapterReply:
    status: int
    answer: str
    citations: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)
    latency_s: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [v if isinstance(v, str) else json.dumps(v) for v in items]


class HttpAdapter:
    def __init__(
        self,
        base_url: str,
        config: AdapterConfig,
        *,
        rate_per_s: float,
        timeout_s: float,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.config = config
        self.min_interval = 1.0 / rate_per_s if rate_per_s > 0 else 0.0
        self._client = client or httpx.Client(timeout=timeout_s, follow_redirects=False)
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None
        self.requests_sent = 0
        headers = dict(config.headers)
        if config.auth_header_env:
            token = os.environ.get(config.auth_header_env, "").strip()
            if not token:
                raise AdapterError(f"{config.auth_header_env} is not set (adapter auth header)")
            headers[config.auth_header_name] = token  # read from env, never written to disk
        self._headers = headers

    def _throttle(self) -> None:
        if self._last is not None and self.min_interval:
            wait = self.min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()

    def send(self, message: str, session_id: str, *, throttle: bool = True) -> AdapterReply:
        if throttle:
            self._throttle()
        url = f"{self.base_url}{self.config.url_path}"
        body = render_body(self.config.body, message, session_id)
        self.requests_sent += 1
        started = time.perf_counter()
        try:
            if self.config.method == "GET":
                response = self._client.get(url, params={"message": message, "session_id": session_id}, headers=self._headers)
            else:
                response = self._client.request(self.config.method, url, content=body.encode("utf-8"), headers=self._headers)
        except httpx.TimeoutException:
            return AdapterReply(status=0, answer="", latency_s=time.perf_counter() - started, error="timeout")
        except httpx.HTTPError as exc:
            return AdapterReply(status=0, answer="", latency_s=time.perf_counter() - started, error=type(exc).__name__)
        latency = time.perf_counter() - started
        try:
            data = response.json()
        except ValueError:
            data = None
        answer = json_path(data, self.config.answer_path) if data is not None else None
        if answer is None:
            answer = "" if not response.is_success else response.text
        return AdapterReply(
            status=response.status_code,
            answer=answer if isinstance(answer, str) else json.dumps(answer),
            citations=_as_text_list(json_path(data, self.config.citations_path)) if data is not None else [],
            context=_as_text_list(json_path(data, self.config.context_path)) if data is not None else [],
            latency_s=latency,
            error="" if response.is_success else f"HTTP {response.status_code}",
        )

    def close(self) -> None:
        self._client.close()
