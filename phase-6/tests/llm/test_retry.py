import openai
import pytest
from conftest import MESSAGES, FakeTransport, connection_error, http_error

from evalpilot.config import RetryConfig
from evalpilot.llm import LlmClient
from evalpilot.llm.retry import backoff_delay, call_with_retry, is_retryable

CFG = RetryConfig(max_attempts=5, base_delay_s=1.0, max_delay_s=30.0)


def _run(errors, cfg=CFG):
    sleeps: list[float] = []
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if errors:
            raise errors.pop(0)
        return "ok"

    result = call_with_retry(fn, cfg, sleep=sleeps.append, rng=lambda: 0.0)
    return result, calls["n"], sleeps


def test_retry_on_429_then_success():
    errors = [http_error(openai.RateLimitError, 429), http_error(openai.RateLimitError, 429)]
    result, calls, sleeps = _run(errors)
    assert result == "ok" and calls == 3
    assert sleeps == [1.0, 2.0]


def test_retry_on_5xx():
    result, calls, _ = _run([http_error(openai.InternalServerError, 503)])
    assert result == "ok" and calls == 2


def test_retry_on_connection_error():
    result, calls, _ = _run([connection_error()])
    assert result == "ok" and calls == 2


def test_no_retry_on_400():
    with pytest.raises(openai.BadRequestError):
        _run([http_error(openai.BadRequestError, 400)])


def test_no_retry_on_auth_error():
    assert not is_retryable(http_error(openai.AuthenticationError, 401))


def test_gives_up_after_max_attempts():
    errors = [http_error(openai.RateLimitError, 429) for _ in range(5)]
    with pytest.raises(openai.RateLimitError):
        _run(errors)


def test_retry_after_header_respected():
    errors = [http_error(openai.RateLimitError, 429, {"retry-after": "7"})]
    _, _, sleeps = _run(errors)
    assert sleeps == [7.0]


def test_backoff_is_capped():
    assert backoff_delay(10, CFG, jitter=0.5) == 30.0


def test_client_retries_and_bills_once(settings):
    transport = FakeTransport(errors=[http_error(openai.RateLimitError, 429)])
    client = LlmClient(settings, "openai", transport=transport, sleep=lambda _s: None)
    client.chat(MESSAGES)
    assert len(transport.requests) == 2
    assert len(client.ledger.entries()) == 1


def test_failed_call_is_not_billed_or_cached(settings):
    transport = FakeTransport(errors=[http_error(openai.BadRequestError, 400)])
    client = LlmClient(settings, "openai", transport=transport, sleep=lambda _s: None)
    with pytest.raises(openai.BadRequestError):
        client.chat(MESSAGES)
    assert client.ledger.entries() == []
    assert not client.chat(MESSAGES).cached
