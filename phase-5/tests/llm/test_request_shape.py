from conftest import MESSAGES

from evalpilot.llm import build_request


def _req(model="gpt-5.4-nano", **kwargs):
    return build_request(model, MESSAGES, max_completion_tokens=400, reasoning_effort="none", **kwargs)


def test_request_has_max_completion_tokens():
    req = _req()
    assert req["max_completion_tokens"] == 400
    assert "max_tokens" not in req


def test_request_has_no_temperature():
    for model in ("gpt-5.4-nano", "gpt-5.4-mini", "llama-3.1-8b-instant"):
        assert "temperature" not in _req(model)


def test_reasoning_models_get_lowest_effort():
    assert _req("gpt-5.4-nano")["reasoning_effort"] == "none"
    assert _req("gpt-5.4-mini")["reasoning_effort"] == "none"


def test_non_reasoning_models_get_no_reasoning_effort():
    assert "reasoning_effort" not in _req("llama-3.1-8b-instant")


def test_json_schema_response_format():
    schema = {"title": "verdict", "type": "object", "properties": {"pass": {"type": "boolean"}}}
    fmt = _req(json_schema=schema)["response_format"]
    assert fmt["type"] == "json_schema"
    assert fmt["json_schema"]["name"] == "verdict" and fmt["json_schema"]["strict"] is True


def test_client_sends_settings_values(settings, paid_client, fake_transport):
    paid_client.chat(MESSAGES)
    sent = fake_transport.requests[0]
    assert sent["max_completion_tokens"] == settings.max_completion_tokens
    assert sent["reasoning_effort"] == settings.reasoning_effort == "none"
    assert "temperature" not in sent
