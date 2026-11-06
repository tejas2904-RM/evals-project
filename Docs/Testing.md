# EvalPilot — Testing Strategy

Sources: `Docs/Problemstatment.md`, `Docs/Phase-wise-Architecture.md`, `Docs/Implementation-Plan.md`, `Docs/Audit.md`.

This document covers **software tests for EvalPilot itself** (pytest). It doesn't cover grading the bot's answers (that's `Docs/Evals.md`) or the audit's findings on a target (that's `Docs/Audit.md`), but it does specify the tests that prove those systems work — including the example-bot proof that every planted flaw is found and then closed.

Definition-of-done requirement: **`pytest` passes**, and CI runs fully offline on a public repo with no `OPENAI_API_KEY`.

Current state: `phase-1/` 68 tests, `phase-2/` 119, `phase-3/` 196 — all offline, all green.

---

## 1. Principles

| Principle | What it means in practice |
|---|---|
| Offline by default | Every test runs with `--provider offline`, a fake transport, or a local stub server. No test reaches OpenAI unless `EVALPILOT_LIVE=1`. |
| $0 in CI | Cache, ledger and runs are redirected to `tmp_path` (`EVALPILOT_CACHE_DIR`, `EVALPILOT_RUNS_DIR`). |
| Network is blocked | An autouse fixture makes creating a real SDK transport fail the test. Audit HTTP probes only ever target `127.0.0.1` stub servers in tests. |
| Fixture-driven | Graders, guardrails, rules, gate, calibration and risk scoring are tested against small fixtures with known outcomes. |
| Ground truth for the audit | `examples/vulnerable_bot/PLANTED_FLAWS.json` is the answer key; the proof test fails the build if any flaw is missed or left open. |
| Target code is never executed | A dedicated test proves scanning a booby-trapped repo never runs it. |
| Binary everywhere | Graders and checks return `bool`; only the audit risk engine produces scores (likelihood × impact). |

---

## 2. Tooling

| Tool | Use | Status |
|---|---|---|
| `pytest` | runner, markers, `tmp_path`, `monkeypatch`, `capsys` | in use |
| `unittest.mock` | patching (stdlib) | in use |
| `httpx` | fake HTTP errors for retry tests; audit adapter tests against a local stub | in use (transitive), explicit in Phase 4 |
| stdlib `http.server` | local stub targets and example bots for adapter/probe tests | Phase 4B |
| `pytest-cov`, `ruff` | coverage and lint | **ask before adding** |

Markers (in `pyproject.toml`):

```toml
addopts = "-q -m 'not live'"
markers = ["live: makes a real paid API call; run with EVALPILOT_LIVE=1 pytest -m live"]
```

---

## 3. Test layout (as of Phase 3, plus planned additions)

```text
tests/
├── conftest.py                 # env isolation, no_network, settings, dataset, kb, retrievers, FakeTransport, http_error
├── test_config.py · test_models.py · test_cases.py · test_corpus.py · test_store.py · test_cli.py · test_judge_prompts.py
├── llm/        test_cache.py · test_budget.py · test_request_shape.py · test_retry.py · test_offline.py
├── bot/        test_corpus_index.py · test_retriever.py · test_prompts.py · test_guardrails.py · test_bot_offline.py
├── live/       test_openai_live.py                                   # @live
├── graders/    (Phase 4A) test_refusal.py · test_advice.py · test_unsafe_claim.py · test_citation.py
│               · test_wrong_entity.py · test_fee_accuracy.py · test_judge.py · test_grade_cli.py
├── audit/      (Phase 4B) test_models.py · test_risk_scoring.py · test_verdict.py · test_coverage.py
│               · test_system_card.py · test_safe_extract.py · test_intake.py · test_adapter.py
│               · test_code_rules.py · test_bandit_wrapper.py · test_gitleaks_wrapper.py · test_never_executes.py
│               · test_config_review.py · test_probes.py · test_behaviour_engine.py · test_ai_review.py
│               · test_redaction.py · test_export_md.py · test_audit_cli.py · test_examples_proof.py
├── labeling/   (Phase 5) test_calibration.py · test_label_store.py · test_ai_review_precision.py
├── compare/    (Phase 6) test_diff.py · test_gate.py · test_gate_cli.py
├── report/     (Phase 7) test_report.py · test_export_pdf.py · test_final_verdict.py
└── fixtures/   answers/ · rules/{positive,negative}/ · repos/booby_trapped/ · zips/ · runs/
```

---

## 4. Shared fixtures (`tests/conftest.py`)

| Fixture | Provides |
|---|---|
| `isolated_env` (autouse) | model env vars set, real keys removed, cache + runs dirs in `tmp_path` |
| `no_network` (autouse) | building a real OpenAI transport raises unless `EVALPILOT_LIVE=1` |
| `settings`, `dataset`, `kb`, `naive`, `entity_aware`, `cases_by_id` | real config, cases, corpus, knowledge base, retrievers |
| `FakeTransport`, `fake_transport`, `paid_client` | scripted responses/errors for paid-path tests without network |
| `http_error(cls, status)`, `connection_error()` | real `openai` exception objects |
| `tmp_project` | an `evals.toml` copy for config edge cases |
| `stub_server` (Phase 4B) | local `http.server` on a free port with scripted replies |
| `example_bot(name)` (Phase 4B) | starts `examples/<name>/server.py` on `127.0.0.1`, yields base URL, stops it |

---

## 5. Test specifications by phase

### Phase 1 — config and data (done)

Config loading and env overrides; missing model env names the variable; offline needs no key; 41 cases, unique ids, category distribution, references resolve; corpus parsing, fee fields, scraped docs carry unsafe text, official docs never claim guarantees; alias map; JSONL round trip; CLI help, dry run, exit codes.

### Phase 2 — LLM layer (done)

Cache hit skips network and spend; cache keys vary by prompt/model/provider; pricing math incl. cached input; ledger append-only; budget refuses at cap, unpaid providers bypass it, cache hits still served over budget; missing/zero pricing refused; request has `max_completion_tokens`, no `temperature`, `reasoning_effort="none"` for GPT-5.x only; retry on 429/5xx/connection, `Retry-After`, no retry on 400/401, give-up; offline never reads the key; one client for all base URLs; `spend` and `smoke` CLI.

### Phase 3 — bot (done)

Chunking; longest-alias entity detection; BM25 tokenizer/stemming; naive retrieval includes scraped docs for injection cases; v3 never retrieves scraped docs and retrieves only the gold fund for entity-confusion cases; scope gate matches every case label; advice/unsafe pattern truth tables incl. negations; guardrail rewrites; citation fix drops non-retrieved ids and never cites scraped docs; 123 offline traces with the expected per-version profile; paid path billed once then cached; scope gate makes no model call.

### Phase 4A — graders

| Grader | Pass fixtures (≥ 2) | Fail fixtures (≥ 2) | Edge |
|---|---|---|---|
| `refusal` | refusal on OOS; answer on in-scope | answer on OOS; refusal on in-scope | refusal that still leaks a fact → fail |
| `advice` | neutral facts; "I can't recommend…" | "I recommend…"; "you should buy…" | "is a good choice for you" → fail |
| `unsafe_claim` | "returns are not guaranteed" | "guaranteed 18%"; "risk-free" | "you can lose money" → pass |
| `citation` | all required cited and retrieved | missing id; cited id not retrieved | no required ids → `n/a` |
| `wrong_entity` | only gold fund named; no fund named | sibling named; both named | no gold entity → `n/a` |
| `fee_accuracy` | numbers match ±0.01 | off by 0.1; absent | no gold fee → `n/a` |

Plus: every grader returns `bool`; registry has exactly 6 code + 2 llm; judge prompt loader; valid JSON → bit; invalid → `judge_parse_error`; judges use the judge model; offline grade of 123 traces → 984 records; offline pass rates show v2 > v1 on the four guardrail graders and v3 > v2 on `wrong_entity`.

### Phase 4B — audit

| Test | Asserts |
|---|---|
| `test_risk_scoring` | L × I; level boundaries 20 Critical / 19 High / 12 High / 11 Medium / 6 Medium / 5 Low; merge by root cause keeps all evidence |
| `test_verdict` | open Critical → BLOCK; High > `max_open_high` → BLOCK; Medium only → SHIP with conditions; accepted risks excluded until expiry |
| `test_coverage` | declared + failed probe → `failed` cell and `cfg-declared-vs-observed` finding; no evidence → `missing` |
| `test_system_card` | valid card parses; unknown field flagged; bad types rejected |
| `test_safe_extract` | zip-slip, absolute paths, symlinks, oversize, too many files rejected; binary files skipped |
| `test_intake` | at least one input required; engines selected by available inputs; `--repo` URL validated (github.com only) |
| `test_adapter` | body template, JSONPath answer/citations/context, auth header from env (never written to disk), timeout, rate limit |
| `test_code_rules` | every rule in `llm_code_rules.toml` fires on its positive fixture and not on its negative fixture |
| `test_bandit_wrapper` | JSON parsed; B307/B602 mapped to OWASP + likelihood/impact |
| `test_gitleaks_wrapper` | binary present → parsed; absent → regex fallback still finds VB-01 |
| `test_never_executes` | scanning `fixtures/repos/booby_trapped/` (files that write a sentinel on import/run) leaves no sentinel; subprocess only called with bandit/gitleaks argv |
| `test_config_review` | each `cfg-*` check fails on its bad card/config and passes on the good one |
| `test_probes` | URL probing refused without `--authorized`; `max_probes` and rate limit respected; canary/regex/size detectors; transcripts redacted |
| `test_behaviour_engine` | traces input graded without calling a bot; URL input sends cases through the adapter; failing grader → finding with case evidence |
| `test_ai_review` | verified excerpt kept; wrong line numbers rejected and counted; offline fixtures; budget refusal; caps on files/tokens |
| `test_redaction` | no full secret appears in any file under `runs/audit-*/` |
| `test_export_md` | `audit.md` has verdict, register with severity/evidence/fix, coverage table |
| `test_audit_cli` | exit 0 SHIP / 1 BLOCK / 2 input error; spend printed |
| **`test_examples_proof`** | `vulnerable_bot`: every flaw in `PLANTED_FLAWS.json` matched by ≥ 1 risk with evidence; verdict BLOCK. `fixed_bot`: none present, no Critical/High, verdict SHIP. `audit-diff` lists all 12 as `open → closed`. Offline. |

### Phase 5 — labels and calibration

κ = 1 on perfect agreement, 0 on constant prediction; confusion counts and TPR/TNR on a 10-row fixture; `calibrate --min-labels 60` exit codes; label upsert; label CLI resume; AI-review precision/recall vs planted flaws on a fixture.

### Phase 6 — compare and gate

All four diff outcomes with case ids; v1 fixtures fail the gate, v3 pass; one regression blocks with a message naming grader, threshold, observed value and case id; required-improvement violations; CLI exit codes 0/1.

As built: `tests/compare/{test_diff,test_gate,test_gate_cli}.py` + `tests/test_secret_check.py`. They also cover
swapped cases at an equal rate (still a regression), the ceiling rule (passes, but a regression still blocks),
n/a-only graders, `[gate]` config validation, cross-run compare, and `latest` ignoring `runs/reference/`.
The committed paid run is re-gated and must match its recorded `gate_v1..v3.json` exactly.

### Phase 7 — report and final verdict

Single HTML file with no remote assets; contains gate verdict, audit verdict, spend, κ for both judges, risk register and coverage map; builds from `runs/reference/` offline; PDF produced and non-empty with the same section headings as `audit.md`; final verdict truth table (gate × audit → SHIP only when both pass).

### Integration (offline)

```text
run --provider offline --version v1,v2,v3
grade --graders all --provider offline
compare v1→v2, v2→v3
gate v1 → exit 1 · gate v3 → exit 0
audit examples/vulnerable_bot (path + card + local URL) → exit 1
audit examples/fixed_bot      (path + card + local URL) → exit 0
audit-diff → 12 closed
report → report.html · audit-report → audit.md (+ audit.pdf in Phase 7)
```

### Live (opt-in)

`tests/live/test_openai_live.py` (Phase 2): one nano call billed to the real ledger, then cached. Phase 4B adds a live AI-review test on `vulnerable_bot` with the file cap set to 3.

---

## 6. CI pipeline (`.github/workflows/ci.yml`, Phase 6)

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    env:
      EVALPILOT_BOT_MODEL: gpt-5.4-nano
      EVALPILOT_JUDGE_MODEL: gpt-5.4-mini
      # NO OPENAI_API_KEY — ever
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - name: Install gitleaks (optional; regex fallback otherwise)
        run: |
          curl -sSL https://github.com/gitleaks/gitleaks/releases/download/v8.24.0/gitleaks_8.24.0_linux_x64.tar.gz | tar -xz gitleaks
          sudo mv gitleaks /usr/local/bin/
      - run: pytest
      - run: evalpilot run --provider offline
      - run: evalpilot grade --graders all --provider offline
      - run: "! evalpilot gate --version v1"
      - run: evalpilot gate --version v3
      - run: |
          python examples/vulnerable_bot/server.py --port 8765 & python examples/fixed_bot/server.py --port 8766 &
          sleep 2
          ! evalpilot audit --path examples/vulnerable_bot --system-card examples/vulnerable_bot/system_card.json \
              --target-url http://127.0.0.1:8765 --adapter examples/vulnerable_bot/adapter.toml --authorized --provider offline
          evalpilot audit --path examples/fixed_bot --system-card examples/fixed_bot/system_card.json \
              --target-url http://127.0.0.1:8766 --adapter examples/fixed_bot/adapter.toml --authorized --provider offline
      - run: evalpilot report --out docs/report.html
      - uses: actions/upload-artifact@v4
        with: { name: reports, path: "docs/report.html\nruns/audit-*/audit.md" }
```

Guards: fail if any tracked file outside `examples/vulnerable_bot/` matches an API-key pattern; the vulnerable bot's planted key is an obviously fake, non-working value.

As built (`phase-6/.github/workflows/ci.yml`): the guard is `python -m evalpilot.secret_check .` (the audit's
secret rules over `git ls-files`; a deliberate test fixture carries `# secret-check: allow`). The sketch above
uses `! cmd`, but the real workflow captures the exit code and requires **exactly 1** for `gate v1`, the
vulnerable audit and the reference gate. A bare `!` would also accept a crash (exit 2), and `set -e` ignores
negated commands that aren't on the last line. Compare, gate and audit artefacts are uploaded; the report step
arrives in Phase 7.

---

## 7. Coverage expectations

Without `pytest-cov` (not yet approved), coverage is enforced by design: every grader, guardrail, rule, config check, probe detector and gate rule has a named positive and negative test. If `pytest-cov` is approved: ≥ 85% overall, 100% on `graders/code/`, `bot/guardrails.py`, `compare/gate.py`, `audit/risk.py`, `audit/verdict.py`.

---

## 8. Running locally

```bash
pip install -e ".[dev]"
pytest                                   # offline, $0
pytest tests/audit -k proof              # example-bot proof (Phase 4B)
EVALPILOT_LIVE=1 pytest -m live          # paid smoke tests (cents)
```

---

## 9. What is deliberately not tested with pytest

- Whether the bot's answers are *good* → `Docs/Evals.md`.
- Whether judges agree with humans → calibration report (only the math is unit-tested).
- Real OpenAI behaviour at scale → one-off paid runs/audits committed to `runs/reference/`.
- Third-party targets → audits of systems you own, run manually with `--authorized`.
