"""Token x price accounting, an append-only spend ledger, and the budget guard."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from evalpilot.llm.types import LedgerEntry, Usage

PER_MILLION = 1_000_000


class BudgetExceeded(RuntimeError):
    pass


class PricingError(RuntimeError):
    pass


def require_pricing(pricing: dict[str, dict[str, float]], model: str) -> dict[str, float]:
    prices = pricing.get(model)
    if not prices or prices.get("input", 0) <= 0 or prices.get("output", 0) <= 0:
        raise PricingError(
            f"No pricing for paid model '{model}'. Add [pricing.\"{model}\"] input/output (USD per 1M tokens) to evals.toml."
        )
    return prices


def cost_usd(prices: dict[str, float], usage: Usage) -> float:
    cached = min(usage.cached_prompt_tokens, usage.prompt_tokens)
    uncached = usage.prompt_tokens - cached
    total = (
        uncached * prices["input"]
        + cached * prices.get("cached_input", prices["input"])
        + usage.completion_tokens * prices["output"]
    )
    return total / PER_MILLION


class Ledger:
    """Append-only JSONL of paid calls; survives restarts so spend is cumulative across runs."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def append(
        self, *, run_id: str, provider: str, model: str, purpose: str, usage: Usage, cost: float
    ) -> LedgerEntry:
        entry = LedgerEntry(
            ts=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            run_id=run_id,
            provider=provider,
            model=model,
            purpose=purpose,
            prompt_tokens=usage.prompt_tokens,
            cached_prompt_tokens=usage.cached_prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=cost,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(entry.model_dump_json() + "\n")
        return entry

    def entries(self) -> list[LedgerEntry]:
        if not self.path.is_file():
            return []
        with self.path.open(encoding="utf-8") as fh:
            return [LedgerEntry.model_validate_json(line) for line in fh if line.strip()]

    def total(self, run_id: str | None = None) -> float:
        return sum(e.cost_usd for e in self.entries() if run_id is None or e.run_id == run_id)


class BudgetGuard:
    def __init__(self, budget_usd: float, ledger: Ledger) -> None:
        self.budget_usd = budget_usd
        self.ledger = ledger

    def remaining(self) -> float:
        return max(0.0, self.budget_usd - self.ledger.total())

    def check(self) -> None:
        spent = self.ledger.total()
        if spent >= self.budget_usd:
            raise BudgetExceeded(
                f"Budget reached: ${spent:.4f} spent of ${self.budget_usd:.2f} (budget_usd in evals.toml). "
                "Paid calls are refused; cached and offline runs still work."
            )


def format_spend(ledger: Ledger, budget_usd: float, run_id: str | None = None) -> str:
    total = ledger.total()
    line = f"Spend: ${total:.4f} / ${budget_usd:.2f} (${max(0.0, budget_usd - total):.4f} left)"
    if run_id is not None:
        line += f" | this run: ${ledger.total(run_id):.4f}"
    return line
