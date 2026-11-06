"""Retry 429 / 5xx (and dropped connections) with jittered exponential backoff."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

import openai

from evalpilot.config import RetryConfig

T = TypeVar("T")


def status_of(exc: BaseException) -> int | None:
    return getattr(exc, "status_code", None)


def is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, openai.APIConnectionError):
        return True
    status = status_of(exc)
    return status is not None and (status == 429 or status >= 500)


def _retry_after(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


def backoff_delay(attempt: int, cfg: RetryConfig, jitter: float) -> float:
    return min(cfg.base_delay_s * 2 ** (attempt - 1) + jitter * cfg.base_delay_s, cfg.max_delay_s)


def call_with_retry(
    fn: Callable[[], T],
    cfg: RetryConfig,
    *,
    sleep: Callable[[float], None] = time.sleep,
    rng: Callable[[], float] = random.random,
) -> T:
    for attempt in range(1, cfg.max_attempts + 1):
        try:
            return fn()
        except Exception as exc:
            if not is_retryable(exc) or attempt == cfg.max_attempts:
                raise
            delay = _retry_after(exc) or backoff_delay(attempt, cfg, rng())
            sleep(min(delay, cfg.max_delay_s))
    raise AssertionError("unreachable")
