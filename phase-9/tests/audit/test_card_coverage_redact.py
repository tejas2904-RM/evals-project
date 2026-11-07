import json

import pytest

from evalpilot.audit.coverage import LAYERS, build_coverage, declared_vs_observed
from evalpilot.audit.models import CheckOutcome
from evalpilot.audit.redact import find_secrets, is_placeholder, mask, redact
from evalpilot.audit.system_card import CardError, SystemCard, load_system_card

FAKE_KEY = "sk-proj-" + "Z" * 8 + "abcdefghijklmnopqrstuv1234"


def test_example_cards_load(examples):
    vuln = load_system_card(examples / "vulnerable_bot" / "system_card.json")
    fixed = load_system_card(examples / "fixed_bot" / "system_card.json")
    assert vuln.unknown_fields() == ["deployment_notes"] and fixed.unknown_fields() == []
    assert vuln.canaries.keys() == fixed.canaries.keys()


def test_card_rejects_bad_nested_field(tmp_path):
    path = tmp_path / "card.json"
    path.write_text(json.dumps({"name": "x", "tools": [{"name": "t", "side_effects": "explode"}]}), encoding="utf-8")
    with pytest.raises(CardError, match="tools.0.side_effects"):
        load_system_card(path)


def test_card_rejects_unreadable_json(tmp_path):
    path = tmp_path / "card.json"
    path.write_text("{nope", encoding="utf-8")
    with pytest.raises(CardError):
        load_system_card(path)


def _check(check_id, passed):
    return CheckOutcome(engine="security", check_id=check_id, passed=passed)


def test_coverage_statuses():
    card = SystemCard(name="x", guardrails_declared=["output_encoding", "pii_redaction", "injection_filter"])
    cells = {c.layer: c for c in build_coverage([_check("probe/LLM10-XSS-01", False), _check("probe/LLM01-DIRECT-01", True)], card)}
    assert set(cells) == set(LAYERS)
    assert cells["output_encoding"].status == "failed"
    assert cells["injection_filter"].status == "verified"
    assert cells["pii_redaction"].status == "declared"
    assert cells["dependency_pinning"].status == "missing"
    assert cells["tool_confirmation"].status == "n/a"  # no write/external tools in the card


def test_failed_beats_passed_for_same_layer():
    cells = {c.layer: c for c in build_coverage([_check("probe/LLM10-XSS-01", True), _check("probe/LLM10-XSS-02", False)], None)}
    assert cells["output_encoding"].status == "failed" and cells["output_encoding"].passed_checks == ["probe/LLM10-XSS-01"]


def test_declared_but_failed_layer_is_a_finding():
    card = SystemCard(name="x", guardrails_declared=["output_encoding"])
    [f] = declared_vs_observed(build_coverage([_check("probe/LLM10-XSS-01", False)], card))
    assert f.check_id == "config/cfg-declared-vs-observed" and f.merge_key == "declared:output_encoding" and f.owasp == "LLM10"


def test_redact_masks_secrets_but_keeps_shape():
    text = f'OPENAI_API_KEY = "{FAKE_KEY}"'
    out = redact(text)
    assert FAKE_KEY not in out and "sk-…1234" in out


@pytest.mark.parametrize("text,rule", [
    (FAKE_KEY, "openai-key"),
    ("AKIA" + "ABCDEFGHIJKLMNOP", "aws-access-key"),
    ("ghp_" + "a" * 36, "github-token"),
    ('api_key = "q8Zr2LmN0pXv7Tb4"', "generic-secret"),  # secret-check: allow
    ("-----BEGIN RSA PRIVATE KEY-----", "private-key"),  # secret-check: allow
])
def test_secret_rules(text, rule):
    assert [m.rule for m in find_secrets(text)] == [rule]


@pytest.mark.parametrize("text", ['api_key = "your-api-key-here"', 'token = os.environ["TOKEN"]', 'password = "xxxxxxxxxxxxxxxx"',
                                  "sk-short", 'secret = "<redacted>"'])
def test_placeholders_are_not_secrets(text):
    assert find_secrets(text) == []


def test_mask_and_placeholder_helpers():
    assert mask("short") == "***"
    assert mask("abcdefghijklmnop") == "abc…mnop"
    assert is_placeholder("CHANGEME-later") and not is_placeholder("q8Zr2LmN0pXv7Tb4")
