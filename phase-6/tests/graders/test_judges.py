import json

import pytest

from evalpilot.graders import GRADER_NAMES, select_graders
from evalpilot.graders.llm.judge import (
    JUDGE_NAMES,
    PARSE_ERROR,
    LlmJudge,
    build_context,
    fill,
    load_judge_prompts,
    offline_key,
    parse_verdict,
)
from evalpilot.llm import LlmClient
from evalpilot.models import Trace


def trace(**kw):
    base = dict(run_id="r", case_id="fee_01", version="v3", query="What is the fee?", retrieved_doc_ids=["bluechip_growth_factsheet"],
                answer="0.62% [bluechip_growth_factsheet]", citations=[], refused=False, model="m", provider="offline")
    return Trace(**{**base, **kw})


def test_registry_has_eight_graders():
    assert len(GRADER_NAMES) == 8 and GRADER_NAMES[-2:] == JUDGE_NAMES


def test_select_graders(settings):
    assert len(select_graders("code", None, settings.judge_prompts_path)) == 6
    client = LlmClient(settings, "offline")
    assert len(select_graders("llm", client, settings.judge_prompts_path)) == 2
    assert len(select_graders("all", client, settings.judge_prompts_path)) == 8
    with pytest.raises(ValueError):
        select_graders("some", client, settings.judge_prompts_path)
    with pytest.raises(ValueError):
        select_graders("llm", None, settings.judge_prompts_path)


def test_prompts_have_placeholders_and_few_shot_examples(settings):
    prompts = load_judge_prompts(settings.judge_prompts_path)
    for name in JUDGE_NAMES:
        body = prompts[name]
        assert "{query}" in body and "{answer}" in body
        assert '"pass": true|false' in body
        assert 'Verdict: {"pass": true' in body and 'Verdict: {"pass": false' in body and "Borderline" in body, name


@pytest.mark.parametrize("content,expected", [
    ('{"pass": true, "reason": "grounded"}', (True, "grounded")),
    ('{"pass": false, "reason": "invented 1.2%"}', (False, "invented 1.2%")),
])
def test_parse_verdict_ok(content, expected):
    assert parse_verdict(content) == expected


@pytest.mark.parametrize("content", ["not json", '{"pass": "yes"}', "[]", '{"reason": "x"}'])
def test_parse_verdict_rejects(content):
    assert parse_verdict(content) is None


def test_fill_keeps_literal_json_braces():
    out = fill('Q={query} A={answer} C={context} S={in_scope} {"pass": true}', query="q", context="c", answer="a", in_scope="true")
    assert out == 'Q=q A=a C=c S=true {"pass": true}'


def test_context_prefers_trace_context_then_kb(kb):
    assert build_context(trace(context=["hello"]), kb) == "hello"
    assert "[bluechip_growth_factsheet] (official)" in build_context(trace(), kb)
    assert build_context(trace(retrieved_doc_ids=[]), kb) == "(no retrieved context)"


def test_offline_judge_uses_fixture_key(settings, kb):
    client = LlmClient(settings, "offline")
    t = trace()
    judge = LlmJudge("judge_grounded", load_judge_prompts(settings.judge_prompts_path)["judge_grounded"], client)
    assert client.has_offline_fixture(offline_key("judge_grounded", t))
    assert judge.grade(None, t, kb).kind == "llm"


def test_unparseable_judge_reply_is_recorded_not_raised(settings, kb, monkeypatch):
    client = LlmClient(settings, "offline")
    judge = LlmJudge("judge_grounded", "{query} {answer}", client)
    monkeypatch.setattr(client._offline, "fixtures", {offline_key("judge_grounded", trace()): "garbage"}, raising=False)
    rec = judge.grade(None, trace(), kb)
    assert not rec.passed and rec.evidence.startswith(PARSE_ERROR)


def test_paid_judge_request_shape(paid_client, fake_transport, settings, kb):
    fake_transport.content = json.dumps({"pass": True, "reason": "ok"})
    judge = LlmJudge("judge_grounded", load_judge_prompts(settings.judge_prompts_path)["judge_grounded"], paid_client)
    assert judge.grade(None, trace(), kb).passed
    req = fake_transport.requests[0]
    assert req["model"] == settings.judge_model
    assert req["response_format"]["json_schema"]["name"] == "judge_verdict"
