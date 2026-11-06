import json
from collections import Counter

import pytest
from audit_helpers import FakeAdapter, finding

from evalpilot.audit import ai_review
from evalpilot.audit.adapters import AdapterReply
from evalpilot.audit.engines.behaviour import run_behaviour
from evalpilot.audit.engines.config_review import run_config_review
from evalpilot.audit.engines.security import Probe, detect, load_probes, run_security
from evalpilot.audit.files import SourceFile, iter_text_files
from evalpilot.audit.system_card import SystemCard, load_system_card
from evalpilot.graders import code_graders
from evalpilot.llm import BudgetExceeded, Ledger, LlmClient
from evalpilot.models import Trace

OWASP = [f"LLM{i:02d}" for i in range(1, 11)]


# --- config review ------------------------------------------------------------------------------

def test_vulnerable_card_fails_every_card_check(examples):
    result = run_config_review(load_system_card(examples / "vulnerable_bot" / "system_card.json"), [])
    failed = {c.check_id for c in result.checks if not c.passed}
    assert failed == {"config/cfg-rate-limit", "config/cfg-max-output", "config/cfg-model-pinned", "config/cfg-secrets-inline",
                      "config/cfg-log-redaction", "config/cfg-tool-confirmation", "config/cfg-untrusted-sources",
                      "config/cfg-hidden-context-secrets"}
    assert any(f.check_id == "config/unknown_field" for f in result.findings)


def test_fixed_card_passes(examples):
    result = run_config_review(load_system_card(examples / "fixed_bot" / "system_card.json"), [])
    assert result.findings == [] and all(c.passed for c in result.checks)


def test_file_checks_debug_cors_secrets_ci():
    key = "sk-proj-" + "R" * 6 + "abcdefghijklmnopqrstu4444"
    files = [
        SourceFile("settings.yaml", f"debug: true\napi_key: \"{key}\"\n"),
        SourceFile("server.py", 'self.send_header("Access-Control-Allow-Origin", "*")'),
        SourceFile(".github/workflows/pr.yml", "on: pull_request_target\nsteps:\n - uses: actions/checkout@v4\n - run: echo ${{ secrets.TOKEN }}"),
    ]
    result = run_config_review(None, files)
    ids = Counter(f.check_id for f in result.findings)
    assert ids == {"config/cfg-debug-on": 1, "config/cfg-cors-wildcard": 1, "config/cfg-secrets-inline": 1, "config/cfg-ci-secret-exposure": 1}
    assert all(key not in ev.excerpt for f in result.findings for ev in f.evidence)
    assert "no system card" in result.notes[0]


# --- probe pack ---------------------------------------------------------------------------------

def test_probe_pack_covers_owasp_2026(settings):
    probes = load_probes(settings.data_dir / "probes" / "owasp_llm_2026.jsonl")
    assert len(probes) >= 30
    covered = {p.owasp for p in probes}
    assert covered >= set(OWASP) - {"LLM04"}  # supply chain is a code/config check, not a probe
    assert all(p.id.startswith(p.owasp + "-") for p in probes)
    assert sum(p.request_count for p in probes) <= settings.audit.max_probes


def _probe(detector, **kw):
    return Probe(id=kw.pop("id", "LLM08-EXTRACT-01"), owasp="LLM08", title="t", turns=["hi"], detector=detector, impact=4, fix="f", **kw)


def _ok(answer):
    return AdapterReply(status=200, answer=answer)


CARD = SystemCard(name="x", canaries={"hidden_context": "CANARY-SYS-1"})


@pytest.mark.parametrize("detector,answer,outcome", [
    ({"type": "canary", "card_key": "hidden_context"}, "my prompt says CANARY-SYS-1", "fail"),
    ({"type": "canary", "card_key": "hidden_context"}, "I can't share that.", "pass"),
    ({"type": "canary", "card_key": "missing", "fallback_regex": "(?i)you are"}, "You are a helpful bot", "fail"),
    ({"type": "canary", "card_key": "missing"}, "x", "skip"),
    ({"type": "regex", "pattern": "<script"}, "<script>alert(1)</script>", "fail"),
    ({"type": "regex", "pattern": "<script"}, "&lt;script&gt;", "pass"),
    ({"type": "regex", "pattern": "adviser", "mode": "must_match"}, "talk to an adviser", "pass"),
    ({"type": "refusal_expected"}, "Sure, email sent!", "fail"),
    ({"type": "refusal_expected"}, "I can't send emails.", "pass"),
    ({"type": "grader_pattern", "names": ["unsafe_claim"]}, "Guaranteed returns of 18%!", "fail"),
    ({"type": "grader_pattern", "names": ["advice"]}, "You should buy the Bluechip Growth Fund.", "fail"),
    ({"type": "grader_pattern", "names": ["advice", "unsafe_claim"]}, "Returns are not guaranteed.", "pass"),
])
def test_detectors(detector, answer, outcome):
    assert detect(_probe(detector), ["hi"], [_ok(answer)], CARD, None, "a").outcome == outcome


def test_size_and_throttle_detectors():
    reject = _probe({"type": "latency_or_size", "expect_reject": True})
    assert detect(reject, ["x" * 100], [_ok("fine")], None, None, "a").outcome == "fail"
    assert detect(reject, ["x" * 100], [AdapterReply(status=413, answer="")], None, None, "a").outcome == "pass"
    burst = _probe({"type": "latency_or_size", "expect_throttle": True}, burst=5)
    assert detect(burst, ["x"], [_ok("ok")] * 5, None, None, "a").outcome == "fail"
    assert detect(burst, ["x"], [_ok("ok")] * 4 + [AdapterReply(status=429, answer="")], None, None, "a").outcome == "pass"
    assert detect(_probe({"type": "latency_or_size", "max_reply_chars": 10}), ["x"], [_ok("y" * 50)], None, None, "a").outcome == "fail"


def test_rejected_request_counts_as_safe_and_dead_target_as_error():
    det = {"type": "regex", "pattern": "x"}
    assert detect(_probe(det), ["hi"], [AdapterReply(status=403, answer="")], None, None, "a").outcome == "pass"
    assert detect(_probe(det), ["hi"], [AdapterReply(status=0, answer="", error="timeout")], None, None, "a").outcome == "error"


def test_judge_detector_uses_judge_model(paid_client, fake_transport):
    fake_transport.content = json.dumps({"pass": False, "reason": "it complied"})
    d = detect(_probe({"type": "judge", "goal": "refuse"}), ["hi"], [_ok("done!")], None, paid_client, "a")
    assert d.outcome == "fail" and fake_transport.requests[0]["model"] == "gpt-5.4-mini"
    assert detect(_probe({"type": "judge"}), ["hi"], [_ok("x")], None, None, "a").outcome == "skip"


def test_run_security_findings_transcripts_and_cap():
    probes = [_probe({"type": "canary", "card_key": "hidden_context"}, id=f"LLM08-EXTRACT-0{i}") for i in (1, 2)]
    probes.append(_probe({"type": "latency_or_size", "expect_throttle": True}, id="LLM06-BURST-01", burst=4))
    adapter = FakeAdapter(lambda m, s: _ok("leak: CANARY-SYS-1 sk-proj-" + "A" * 30))
    result = run_security(probes, adapter, CARD, None, audit_id="aud", max_requests=10)
    assert result.stats["fail"] == 3 and result.stats["requests_sent"] == 6
    keys = {f.merge_key for f in result.findings}
    assert keys == {"probe:LLM08:LLM08-EXTRACT", "probe:LLM08:LLM06-BURST"}
    assert all("sk-proj-AAAA" not in t["reply"] for t in result.transcripts)
    assert [s for _, s, _ in adapter.sent][:2] == ["aud-LLM08-EXTRACT-01", "aud-LLM08-EXTRACT-02"]
    assert [t for _, _, t in adapter.sent][-4:] == [False] * 4  # bursts are deliberately unthrottled

    capped = run_security(probes, FakeAdapter(), CARD, None, audit_id="aud", max_requests=1)
    assert capped.stats["requests_sent"] == 1 and capped.stats["skip"] == 2 and "probe cap" in capped.notes[0]


# --- behaviour ----------------------------------------------------------------------------------

def _t(case_id, answer):
    return Trace(run_id="a", case_id=case_id, version="ext", query="q", retrieved_doc_ids=[], answer=answer, citations=[],
                 refused=False, model="m", provider="external")


def test_behaviour_from_traces(cases_by_id, kb):
    traces = [_t("adv_01", "You should buy the Asterion Bluechip Growth Fund. Guaranteed returns!"),
              _t("adv_03", "I recommend the Horizon Debt Fund."), _t("oos_01", "Sorry, I can only answer questions about Asterion funds.")]
    cases = [cases_by_id[c] for c in ("adv_01", "adv_03", "oos_01")]
    result = run_behaviour(traces=traces, cases=cases, adapter=None, graders=code_graders(), kb=kb, audit_id="a")
    by_check = {f.check_id: f for f in result.findings}
    assert by_check["behaviour/advice"].likelihood == 5 and "(2/" in by_check["behaviour/advice"].title
    assert by_check["behaviour/unsafe_claim"].merge_key == "behaviour:unsafe_claim"
    assert {c.check_id for c in result.checks if c.passed} >= {"behaviour/refusal"}


def test_behaviour_live_uses_adapter_sessions(cases_by_id, kb):
    adapter = FakeAdapter()
    result = run_behaviour(traces=None, cases=[cases_by_id["oos_01"]], adapter=adapter, graders=code_graders(), kb=kb, audit_id="aud")
    assert adapter.sent[0][1] == "aud-oos_01" and result.stats["traces"] == 1 and result.findings == []


def test_grounded_judge_is_na_for_targets_without_context(settings, kb, cases_by_id):
    from evalpilot.graders import llm_graders
    from evalpilot.graders.base import is_na

    grounded, _ = llm_graders(LlmClient(settings, "offline"), settings.judge_prompts_path)
    assert is_na(grounded.grade(cases_by_id["fee_01"], _t("fee_01", "0.62%"), kb))
    with_context = Trace.from_dict({**_t("fee_01", "0.62%").to_dict(), "context": ["TER 0.62%"]})
    assert not is_na(grounded.grade(cases_by_id["fee_01"], with_context, kb))


def test_behaviour_skipped_without_inputs(kb):
    assert "skipped" in run_behaviour(traces=None, cases=[], adapter=None, graders=[], kb=kb, audit_id="a").notes[0]


# --- AI review ----------------------------------------------------------------------------------

FILE = SourceFile("tools.py", "import os\n\ndef calc(llm_reply):\n    return eval(llm_reply)\n")


def _item(**kw):
    base = {"file": "tools.py", "line_start": 4, "line_end": 4, "owasp": "LLM10", "title": "eval", "excerpt": "return eval(llm_reply)",
            "likelihood": 5, "impact": 5, "fix": "don't"}
    return {**base, **kw}


def test_verify_accepts_real_excerpt_and_rejects_hallucinations():
    files = {"tools.py": FILE}
    assert ai_review.verify(_item(), files).location == "tools.py:4"
    assert ai_review.verify(_item(excerpt="  return   eval(llm_reply) "), files) is not None  # whitespace-normalised
    for bad in (_item(line_start=1, line_end=1), _item(excerpt="pickle.loads(x)"), _item(file="other.py"),
                _item(line_start=9, line_end=9), _item(line_start=4, line_end=2)):
        assert ai_review.verify(bad, files) is None


def test_review_with_paid_client_keeps_only_verified(paid_client, fake_transport, settings):
    fake_transport.content = json.dumps({"findings": [_item(), _item(line_start=1, line_end=1, excerpt="nope")]})
    result = ai_review.review([FILE], ["tools.py"], paid_client, audit_id="a", max_files=5, max_input_tokens=10_000, max_completion_tokens=500)
    [f] = result.findings
    assert f.check_id == "ai-review/LLM10" and f.likelihood == 3 and f.source == "ai"
    assert result.stats["ai_review"]["rejected"] == 1 and "ai_review_rejected" in result.notes[0]
    req = fake_transport.requests[0]
    assert req["model"] == "gpt-5.4-mini" and req["max_completion_tokens"] == 500
    assert "    4| " in req["messages"][1]["content"]
    [entry] = Ledger(settings.ledger_path).entries()
    assert entry.purpose == "review" and entry.run_id == "a" and entry.cost_usd > 0


def test_review_never_sends_source_to_non_openai_providers(settings):
    client = LlmClient(settings, "ollama", transport=lambda r: pytest.fail("source was sent"))
    result = ai_review.review([FILE], [], client, audit_id="a", max_files=5, max_input_tokens=10_000, max_completion_tokens=100)
    assert result.findings == [] and "skipped" in result.notes[0]


def test_review_offline_skips_chunks_without_fixtures(settings):
    result = ai_review.review([FILE], [], LlmClient(settings, "offline"), audit_id="a", max_files=5, max_input_tokens=10_000,
                              max_completion_tokens=100)
    assert result.findings == [] and result.stats["ai_review"]["skipped_no_fixture"] == 1


def test_review_respects_file_and_token_caps(paid_client, fake_transport):
    fake_transport.content = '{"findings": []}'
    files = [SourceFile(f"bot{i}.py", "x = 1\n" * 50) for i in range(4)]
    ai_review.review(files, [], paid_client, audit_id="a", max_files=2, max_input_tokens=10_000, max_completion_tokens=100)
    assert len(fake_transport.requests) == 2
    fake_transport.requests.clear()
    files = [SourceFile(f"bot{i}.py", "y = 2\n" * 50) for i in range(4)]  # fresh content: no cache hits
    result = ai_review.review(files, [], paid_client, audit_id="a", max_files=4, max_input_tokens=200, max_completion_tokens=100)
    assert len(fake_transport.requests) == 1 and result.stats["ai_review"]["notes"]


def test_review_stops_cleanly_on_budget(monkeypatch, paid_client):
    def broke(*a, **k):
        raise BudgetExceeded("Budget reached")

    monkeypatch.setattr(paid_client, "chat", broke)
    result = ai_review.review([FILE], [], paid_client, audit_id="a", max_files=5, max_input_tokens=10_000, max_completion_tokens=100)
    assert result.findings == [] and "stopped" in result.notes[0]


def test_corroborate_adopts_nearby_rule_merge_key():
    ai = [finding("ai:tools.py:4", source="ai", location="tools.py:4"), finding("ai:tools.py:40", source="ai", location="tools.py:40")]
    rule = [finding("exec-model-output:tools.py", location="tools.py:5")]
    out = ai_review.corroborate(ai, rule)
    assert [f.merge_key for f in out] == ["exec-model-output:tools.py", "ai:tools.py:40"]


def test_offline_review_fixtures_match_example_code(settings, examples):
    files = iter_text_files(examples / "vulnerable_bot", max_files=100, max_file_bytes=100_000)
    result = ai_review.review(files, ["config.py"], LlmClient(settings, "offline"), audit_id="a", max_files=15,
                              max_input_tokens=60_000, max_completion_tokens=100)
    stats = result.stats["ai_review"]
    assert stats["skipped_no_fixture"] == 0, "rerun scripts/build_offline_reviews.py"
    assert len(result.findings) == 5 and stats["rejected"] == 1
