import dataclasses

import pytest
from conftest import MESSAGES, FakeTransport

from evalpilot.llm import BudgetExceeded, Ledger, LlmClient, PricingError, Usage
from evalpilot.llm.budget import cost_usd, format_spend, require_pricing


def test_price_computation(settings):
    prices = require_pricing(settings.pricing, "gpt-5.4-nano")
    usage = Usage(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert cost_usd(prices, usage) == pytest.approx(0.20 + 1.25)


def test_cached_input_billed_at_cached_rate(settings):
    prices = require_pricing(settings.pricing, "gpt-5.4-mini")
    usage = Usage(prompt_tokens=1_000_000, cached_prompt_tokens=400_000, completion_tokens=0)
    assert cost_usd(prices, usage) == pytest.approx(0.6 * 0.75 + 0.4 * 0.075)


def test_ledger_records_paid_call(paid_client):
    response = paid_client.chat(MESSAGES, run_id="r1")
    entries = paid_client.ledger.entries()
    assert len(entries) == 1
    assert entries[0].run_id == "r1" and entries[0].model == "gpt-5.4-nano"
    # 1000 in x $0.20/M + 200 out x $1.25/M
    assert response.cost_usd == pytest.approx(0.00045)
    assert paid_client.ledger.total() == pytest.approx(0.00045)


def test_ledger_is_append_only_and_sums(paid_client):
    paid_client.chat(MESSAGES, run_id="a")
    paid_client.chat([{"role": "user", "content": "different"}], run_id="b")
    ledger = paid_client.ledger
    assert len(ledger.entries()) == 2
    assert ledger.total() == pytest.approx(ledger.total("a") + ledger.total("b"))


def _fill_ledger(ledger: Ledger, usd: float) -> None:
    ledger.append(run_id="old", provider="openai", model="gpt-5.4-mini", purpose="judge", usage=Usage(), cost=usd)


def test_budget_refuses_at_cap(settings, paid_client, fake_transport):
    _fill_ledger(paid_client.ledger, settings.budget_usd)
    with pytest.raises(BudgetExceeded, match=r"\$3\.0000 spent of \$3\.00"):
        paid_client.chat(MESSAGES)
    assert fake_transport.requests == []


def test_budget_allows_just_below_cap(settings, paid_client, fake_transport):
    _fill_ledger(paid_client.ledger, settings.budget_usd - 0.01)
    paid_client.chat(MESSAGES)
    assert len(fake_transport.requests) == 1


def test_cache_hits_still_served_over_budget(settings, paid_client, fake_transport):
    paid_client.chat(MESSAGES)
    _fill_ledger(paid_client.ledger, settings.budget_usd)
    assert paid_client.chat(MESSAGES).cached


@pytest.mark.parametrize("provider", ["groq", "ollama"])
def test_budget_bypassed_for_unpaid_provider(settings, provider):
    transport = FakeTransport()
    client = LlmClient(settings, provider, transport=transport)
    _fill_ledger(client.ledger, settings.budget_usd + 1)
    response = client.chat(MESSAGES)
    assert response.cost_usd == 0.0
    assert len(client.ledger.entries()) == 1  # only the filler row; unpaid calls are not billed


def test_paid_call_without_pricing_refused(settings, fake_transport):
    no_prices = dataclasses.replace(settings, pricing={})
    client = LlmClient(no_prices, "openai", transport=fake_transport)
    with pytest.raises(PricingError, match="gpt-5.4-nano"):
        client.chat(MESSAGES)
    assert fake_transport.requests == []


def test_zero_pricing_counts_as_missing(settings):
    with pytest.raises(PricingError):
        require_pricing({"m": {"input": 0.0, "output": 0.0}}, "m")


def test_format_spend(tmp_path):
    ledger = Ledger(tmp_path / "spend.jsonl")
    assert format_spend(ledger, 3.0) == "Spend: $0.0000 / $3.00 ($3.0000 left)"
    ledger.append(run_id="r", provider="openai", model="m", purpose="bot", usage=Usage(), cost=0.25)
    assert format_spend(ledger, 3.0, "r") == "Spend: $0.2500 / $3.00 ($2.7500 left) | this run: $0.2500"
