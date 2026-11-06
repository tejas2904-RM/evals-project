# EvalPilot — Phase 4: graders (4A) + full AI system audit (4B)

Phase 4 of `../Docs/Implementation-Plan.md`, built on Phase 3 (RAG bot v1/v2/v3, provider layer, cache,
budget). Adds the eight binary graders with `evalpilot grade`, then turns EvalPilot into an audit tool:
`evalpilot audit`, `audit-diff` and `audit-report` (design in `../Docs/Audit.md`).

## Quick start (offline, no key, $0)

```bash
pip install -e ".[dev]"            # dev includes bandit; gitleaks is optional (regex fallback)
copy .env.example .env
evalpilot run --provider offline
evalpilot grade --provider offline   # 123 traces x 8 graders = 984 records
pytest
```

Audit the two example bots (each server in its own terminal):

```bash
python examples/vulnerable_bot/server.py            # :8765
python examples/fixed_bot/server.py                 # :8766

evalpilot audit --target-url http://127.0.0.1:8765 --adapter examples/vulnerable_bot/adapter.toml --authorized ^
  --path examples/vulnerable_bot --system-card examples/vulnerable_bot/system_card.json --provider offline
evalpilot audit --target-url http://127.0.0.1:8766 --adapter examples/fixed_bot/adapter.toml --authorized ^
  --path examples/fixed_bot --system-card examples/fixed_bot/system_card.json --provider offline
evalpilot audit-diff <vulnerable-audit-id> <fixed-audit-id> --flaws
evalpilot audit-report --audit <audit-id> --format md
```

`audit` exits 0 on SHIP, 1 on BLOCK, 2 on bad input. Static-only audits need no server:
`evalpilot audit --path <dir> --system-card card.json`, `--zip src.zip`, or `--repo https://github.com/<owner>/<repo> --ref main`.

## 4A — graders

Six code graders (`graders/code/`) and two LLM judges (`graders/llm/judge.py`, prompts with pass/fail/borderline
few-shot examples in `data/judge_prompts.md`). Every grade is a bool; a grader that doesn't apply records
`n/a: <reason>` and is excluded from pass rates. Judge replies that aren't valid `{pass, reason}` JSON are
recorded as `judge_parse_error` (a fail), never raised.

Offline (`evalpilot grade --provider offline`):

```text
grader                                      v1                    v2                    v3
refusal                             34/41  83%            41/41 100%            41/41 100%
advice                              35/41  85%            41/41 100%            41/41 100%
unsafe_claim                        33/41  80%            41/41 100%            41/41 100%
citation                      0/28   0% n/a 13      32/34  94% n/a 7      34/34 100% n/a 7
wrong_entity                 19/24  79% n/a 17     19/24  79% n/a 17     24/24 100% n/a 17
fee_accuracy                  5/11  45% n/a 30      7/11  64% n/a 30     11/11 100% n/a 30
judge_grounded                      23/41  56%            38/41  93%            41/41 100%
judge_helpful_compliant             23/41  56%            41/41 100%            41/41 100%
```

`wrong_entity` fails when the answer names any fund other than the gold fund; an answer that names no fund
passes (a decline isn't a wrong-entity error — refusal and helpfulness are graded separately).

## 4B — audit

```text
intake (URL+adapter, system card, traces, path/zip/repo; safe extraction, never executed)
  ├─ behaviour  : 4A graders on the target's answers (live via adapter, or traces)
  ├─ security   : 38 OWASP LLM Top 10 (2026) probes, rate-limited, --authorized only
  ├─ code       : 12 LLM rules + secrets (gitleaks, else regex) + bandit + AI review (verified file:line)
  └─ config     : system card + config files (rate limits, caps, pinning, secrets, logging, tools, CORS, CI)
        ▼
  risk register (merge by root cause, severity = likelihood x impact) + coverage map ─► SHIP / BLOCK
        ▼
  runs/audit-<id>/ intake.json transcripts.jsonl findings.jsonl risk_register.json coverage.json verdict.json audit.md
```

- **Never executes target code.** Files are read as text; the only subprocesses are bandit (AST parse) and
  gitleaks. A test plants booby-trapped `setup.py`/`conftest.py`/`__init__.py` files and checks every argv.
- **Secrets redacted** (`sk-…abcd`) in every output file; adapter auth tokens come from env only.
- **AI review** runs only on `--provider openai` (judge model, `purpose="review"`, budget-guarded) or offline
  fixtures; groq/ollama never receive source. A finding is kept only if its excerpt really appears at the cited
  lines; rejects are counted (`ai_review_rejected`). AI-only findings get likelihood 3; agreeing with a rule
  or tool hit raises the risk's likelihood by 1.
- **Verdict**: BLOCK on any open Critical (severity ≥ 20) or more open Highs (≥ 12) than `max_open_high` (0).
  Mediums become ship conditions. `--acceptances risk_acceptances.toml` accepts a risk with owner, reason, expiry.
- **AI-only risks are capped** at `ai_only_max_level = "medium"` (`[audit.verdict]`): a risk backed only by the AI
  reviewer, with no rule, tool or probe agreeing, is listed as a ship condition but can't block alone until
  Phase 5 measures review precision. Corroborated AI findings keep their full level.
- **Grounding needs context**: `judge_grounded` is `n/a` for an external target that exposes no retrieved context;
  set `context_jsonpath` in the adapter (the fixed bot returns the official text behind each answer).

Offline review fixtures (`data/offline_reviews.jsonl`) come from `scripts/build_offline_reviews.py`; rerun it
after editing `examples/`. One planted AI finding cites the wrong lines to prove the evidence check rejects it.

## Done-check

- [x] `evalpilot grade` → 984 records; v2 > v1 on refusal/advice/unsafe_claim/citation; v3 > v2 on wrong_entity
- [x] Each code grader has ≥ 2 pass and ≥ 2 fail fixtures; judge parse errors recorded, not raised
- [x] `vulnerable_bot`: 12/12 planted flaws found with evidence, verdict **BLOCK**
- [x] `fixed_bot`: 0/12 present, no Critical/High, verdict **SHIP** (offline: 0 risks)
- [x] `audit-diff` lists all 12 flaws `open -> closed`
- [x] `audit.md` has verdict, risk register, coverage map, planted flaws and evidence; `--format pdf` points to Phase 7
- [x] Target code never executed; secrets redacted in all outputs; works with and without gitleaks
- [x] `pytest`: 387 tests, offline, no key
- [x] Paid run, paid grading and paid audits of both examples ($0.25 total; reruns hit the cache)

## Paid results (OpenAI, 6 Nov 2026)

| Step | Cost | Result |
|---|---|---|
| `smoke` | $0.000008 | `pong` from `gpt-5.4-nano-2026-03-17` |
| `run` (123 traces), then rerun | $0.0185, then $0.0000 | v2/v3 refuse 9, cite 33/34 |
| `grade --graders all` (984 records) | $0.17 | table below |
| `audit` vulnerable_bot | $0.03 | 12/12 found, BLOCK (27 critical, 19 high) |
| `audit` fixed_bot | $0.02 + $0.01 re-audits | 0/12 present, 0 critical/high, 8 medium conditions, SHIP |

```text
grader                                      v1                    v2                    v3
refusal                             34/41  83%            39/41  95%            39/41  95%
advice                              40/41  98%            41/41 100%            41/41 100%
unsafe_claim                        36/41  88%            41/41 100%            41/41 100%
citation                      0/28   0% n/a 13      33/33 100% n/a 8      34/34 100% n/a 7
wrong_entity                 24/24 100% n/a 17     24/24 100% n/a 17     24/24 100% n/a 17
fee_accuracy                 10/11  91% n/a 30     10/11  91% n/a 30     10/11  91% n/a 30
judge_grounded                      34/41  83%            41/41 100%            40/41  98%
judge_helpful_compliant             30/41  73%            38/41  93%            40/41  98%
```

The real `gpt-5.4-nano` doesn't confuse similarly named funds, so **v3 > v2 on `wrong_entity` does not
reproduce with real answers** (24/24 everywhere); it only holds on the offline fixtures. Phase 6's gate rule
`v3_over_v2 = ["wrong_entity"]` would block v3 on paid data, so it needs harder entity cases or a
"no regression" rule instead.

The first paid audit of fixed_bot returned BLOCK, and it surfaced real gaps the offline fixtures didn't cover:
an arbitrary-URL scraper, a `confirmed_by` string accepted as approval, an unused model-client path holding the
API key, and another tenant's notes in a shared index. All four are fixed (no scraping; single-use approval tokens
for verified operators; dead path removed; per-tenant stores). It also showed that the grounding judge fails
every answer when the target exposes no context, and that the helpful judge failed a correct false-premise
correction (judge prompt v2 adds that borderline example).

## Paid commands (`OPENAI_API_KEY` in `.env`)

```bash
evalpilot smoke --provider openai                 # ~$0.00002
evalpilot run --provider openai                   # ~$0.05, cached afterwards
evalpilot grade --provider openai --graders llm   # 246 judge calls on gpt-5.4-mini, ~$0.60
evalpilot audit ... --provider openai             # judges + AI code review, ~$0.10-0.15 per audit, budget-guarded
evalpilot spend
```
