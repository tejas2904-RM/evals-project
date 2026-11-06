# EvalPilot — Phase 2: provider layer, budget, cache, retry

Phase 2 of `../Docs/Implementation-Plan.md`. Builds on Phase 1 (skeleton, config, 41 cases, corpus) and adds
one OpenAI-compatible client that can talk to OpenAI, Groq, Ollama or a keyless offline stub, with a disk
cache, a budget guard and retries.

## Quick start

```bash
pip install -e ".[dev]"
copy .env.example .env          # add OPENAI_API_KEY only if you want paid calls
pytest                          # offline, $0
```

Optional paid check (one tiny `gpt-5.4-nano` call, about $0.00002):

```bash
evalpilot smoke --provider openai
evalpilot smoke --provider openai   # second time: cached, $0
evalpilot spend
```

## Call pipeline

```text
LlmClient.chat(messages)
  offline provider?          -> fixture / stub reply, $0, nothing cached or billed
  disk cache hit?            -> replay, $0
  paid provider:
    pricing in evals.toml?   -> else PricingError, no call
    ledger total < budget?   -> else BudgetExceeded, no call
  network call (retry 429 / 5xx / dropped connection, backoff + Retry-After)
  paid: tokens x price -> append to .cache/spend.jsonl
  write response to .cache/llm/
```

## What's new vs Phase 1

| Path | Purpose |
|---|---|
| `src/evalpilot/llm/client.py` | `LlmClient`, `build_request` (no `temperature`, `max_completion_tokens`, `reasoning_effort` for GPT-5.x / o-series only) |
| `src/evalpilot/llm/providers.py` | one `openai.OpenAI` client per base URL; `OfflineResponder` reads `data/offline_responses.jsonl` |
| `src/evalpilot/llm/cache.py` | SHA-256 keyed on provider + full request; atomic writes |
| `src/evalpilot/llm/budget.py` | pricing, cost (cached input billed at cached rate), append-only ledger, `BudgetGuard`, spend line |
| `src/evalpilot/llm/retry.py` | jittered exponential backoff, capped at `max_delay_s`, honours `Retry-After` |
| `src/evalpilot/cli.py` | rewritten with typer; `spend` and `smoke` implemented; `run` prints spend |
| `evals.toml` | real GPT-5.4 prices, `reasoning_effort = "none"`, `[retry]`, offline fixtures path |

## Pricing (USD per 1M tokens, from the OpenAI pricing page)

| Model | Input | Cached input | Output |
|---|---|---|---|
| gpt-5.4-nano (bot) | 0.20 | 0.02 | 1.25 |
| gpt-5.4-mini (judge) | 0.75 | 0.075 | 4.50 |

## Commands

| Command | Status |
|---|---|
| `run --dry-run` | validates data, prints plan and spend |
| `spend` | per-model calls and cost, total vs `budget_usd` |
| `smoke --provider X [--judge]` | one tiny call; verifies auth, request shape, cache, billing |
| `grade`, `label`, `calibrate`, `compare`, `gate`, `report`, `audit`, `audit-diff`, `audit-report` | name the phase that implements them |

## Done-check

- [x] Rerunning an identical call costs $0 (cache test + ledger proof)
- [x] `evalpilot spend` prints `Spend: $x.xxxx / $3.00`
- [x] Budget refusal is a clear message and non-zero exit; cached calls still served
- [x] Offline needs no key and never reads `OPENAI_API_KEY`; tests block real network
- [ ] Paid smoke call logged (run `evalpilot smoke --provider openai` once you've added your key)

## Revised build plan

The plan now adds a full AI system audit (see `../Docs/Audit.md`). Phase 4 = 4A graders + 4B audit
(intake, behaviour evals, OWASP LLM Top 10 2026 probes, code scan, config review, risk register,
coverage map, ship/block verdict, Markdown export, `examples/vulnerable_bot` and `examples/fixed_bot`).
Then 5 calibration, 6 compare + gate + CI, 7 HTML report + audit PDF + final verdict. The `audit`,
`audit-diff` and `audit-report` commands are stubs here that point to Phase 4.
