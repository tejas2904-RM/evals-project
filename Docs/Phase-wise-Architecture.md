# EvalPilot — Phase-wise Architecture

Sources: `Docs/Problemstatment.md` (including the **Extension: Full AI System Audit**), `Docs/Audit.md`.

This document turns the problem statement into a **phased system architecture**. Each phase is independently shippable, maps to a CLI surface, and is gated by tests plus cost/offline constraints. Later phases consume artifacts from earlier ones; they don't rewrite the core pipeline. Each phase is built in its own folder (`phase-1/`, `phase-2/`, …), starting from a copy of the previous phase.

| Phase | Scope | Status |
|---|---|---|
| 1 | Skeleton, config, data contracts | done (`phase-1/`) |
| 2 | Provider layer, budget, cache, retry | done (`phase-2/`) |
| 3 | RAG bot v1 / v2 / v3 | done (`phase-3/`) |
| 4 | **4A** 8 binary graders · **4B** Full AI System Audit (intake, 4 engines, risk engine, example bots) | done (`phase-4/`) |
| 5 | Human labels, judge calibration, AI-review precision | built (`phase-5/`); owner labels pending |
| 6 | Run compare and release gate | built (`phase-6/`); CI not yet run on GitHub |
| 7 | HTML report, audit export (Markdown + PDF), final ship/block verdict, definition of done | built (`phase-7/`); final verdict v3 BLOCK pending owner labels; Pages not yet enabled |
| 8 | Backend API (FastAPI) deployed on **Render** | built (`phase-8/`); not yet deployed |
| 9 | Frontend web app deployed on **Vercel**, talking to the Render API | planned |

---

## 0. System at a glance

EvalPilot is a **Python CLI** with two jobs:

1. **Evals** — run a fixed eval set through a fictional mutual-fund FAQ RAG bot, grade answers on binary failure modes, calibrate LLM judges against human labels, gate releases, and emit a single-file HTML report.
2. **Audit** — point it at any LLM system (bot URL, system card, traces, public repo or zip) and get a risk register with evidence and fixes, a guardrail coverage map and a ship/block verdict, exported to Markdown/PDF.

```text
                ┌──────────────────────────────────────────────────────────────────────┐
                │                            evalpilot CLI                             │
                │ run | grade | label | calibrate | compare | gate | report            │
                │ audit | audit-diff | audit-report | spend | smoke                    │
                └──────┬───────────────────────────────┬──────────────────────┬────────┘
                       │                               │                      │
                       ▼                               ▼                      ▼
        ┌──────────────────────────┐   ┌──────────────────────────┐   ┌───────────────────┐
        │ Provider + budget (P2)   │   │ Store (disk)             │   │ Audit intake (4B) │
        │ openai | groq | ollama   │   │ cases, corpus, traces,   │   │ URL+adapter, card,│
        │ offline · cache · retry  │   │ grades, labels, audits   │   │ traces, repo/zip  │
        └────────────┬─────────────┘   └────────────┬─────────────┘   └─────────┬─────────┘
                     │                              │                           │
                     ▼                              │            ┌──────────────┼──────────────┬───────────────┐
        ┌──────────────────────────┐                │            ▼              ▼              ▼               ▼
        │ SUT: RAG bot v1/v2/v3    │                │      Behaviour      Security probes   Code scan      Config review
        │ (P3)                     │                │      evals          OWASP LLM 2026    gitleaks,      system card +
        └────────────┬─────────────┘                │      (graders)      canary/regex/     bandit, rules, config files
                     ▼                              │                     judge             AI review
        ┌──────────────────────────┐                │            └──────────────┼──────────────┴───────────────┘
        │ 8 binary graders (4A)    │◄───────────────┤                           ▼
        │ 6 code + 2 LLM judges    │                │                 ┌───────────────────┐
        └────────────┬─────────────┘                │                 │ Risk engine (4B)  │
                     ▼                              │                 │ L × I, evidence,  │
        ┌──────────────────────────┐                │                 │ fix, coverage map │
        │ Labels + calibration (5) │◄───────────────┘                 └─────────┬─────────┘
        └────────────┬─────────────┘                                            │
                     ▼                                                          │
        ┌──────────────────────────┐                                            │
        │ Compare + gate (6)       │──► CI exit ≠ 0 if blocked                  │
        └────────────┬─────────────┘                                            │
                     ▼                                                          ▼
        ┌──────────────────────────────────────────────────────────────────────────────┐
        │ Report + final verdict (7): HTML (GitHub Pages) · audit.md · audit.pdf       │
        │ SHIP only if release gate passes AND audit verdict is SHIP                   │
        └──────────────────────────────────────────────────────────────────────────────┘
```

### Constraints that apply to every phase

| Constraint | Rule |
|---|---|
| Paid surface | OpenAI API only. Total project spend **under $5**. Soft cap `budget_usd = 3.00` in `evals.toml`. |
| What OpenAI is used for | The bot under test (gpt-5.4-nano), LLM judges and AI code review (gpt-5.4-mini). Nothing else. |
| Models | Names from env vars (`EVALPILOT_BOT_MODEL`, `EVALPILOT_JUDGE_MODEL`). |
| GPT-5.x | No `temperature`. Use `max_completion_tokens` and the lowest reasoning effort the model accepts (`"none"` for gpt-5.4-nano/mini). |
| Client | **One** OpenAI-compatible client; `base_url` switches `openai` / `groq` / `ollama`. |
| Offline | `--provider offline` works with **no key** for evals *and* audits. Public CI never sees `OPENAI_API_KEY`. |
| Cache | Disk cache of every LLM response. Unchanged inputs cost $0 on rerun. |
| Secrets | `OPENAI_API_KEY` from gitignored `.env` only. Secrets found by the audit are redacted in every output. |
| Tools | Open-source / free only: Python libraries, gitleaks, bandit. Report hosted free on GitHub Pages. |
| Checks | Binary pass/fail graders and checks; **no 1–5 quality scores**. Only the audit's risk engine scores, as likelihood × impact. |
| Target code | The audit **never executes** code it scans. |

### Failure modes the eval side must prove

| Failure | Grader | Kind |
|---|---|---|
| Out-of-scope answers (should refuse) | `refusal` | code |
| Fund recommendations / advice (compliance) | `advice` | code |
| Unsafe claims ("guaranteed returns", scraped injection) | `unsafe_claim` | code |
| Missing citations | `citation` | code |
| Wrong fund / entity | `wrong_entity` | code |
| Wrong fees / numeric facts | `fee_accuracy` | code |
| Claims not supported by retrieved docs | `judge_grounded` | LLM |
| Not helpful, or not compliant | `judge_helpful_compliant` | LLM |

### Risks the audit side must surface

The ten OWASP Top 10 for LLM Applications **2026** categories — LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Excessive Agency, LLM04 Supply Chain, LLM05 Data and Model Poisoning, LLM06 Unbounded Consumption, LLM07 Misinformation, LLM08 Hidden Context Exposure, LLM09 Vector and Embedding Weaknesses, LLM10 Improper Output Handling — plus the six bot failure modes above. Details in `Docs/Audit.md`.

---

## Phase 1 — Skeleton, config, and data contracts (done)

**Goal:** a runnable repo that loads cases, config, and secrets without calling a paid API.

**Built:** `pyproject.toml` (CLI entry `evalpilot`), `evals.toml`, `.env.example`, `.gitignore`; `models.py` (`Case`, `Doc`, `Trace`, `GradeRecord`, `Label`), `config.py`, `data.py` (loaders + cross-reference checks), `store.py`; 41 cases across 7 categories; an 11-document corpus for the fictional **Asterion Mutual Fund** (7 fund factsheets, 2 service docs, 2 scraped docs with injected "guaranteed returns" claims); judge prompt skeletons.

**Decision:** standard library only in Phase 1 (dataclasses, argparse, tomllib). Approved afterwards to add pydantic, typer and python-dotenv from Phase 2 onward.

**Exit criteria met:** pytest green (68 tests), `.env` gitignored, offline needs no key, $0.

---

## Phase 2 — Provider layer, budget, cache, retry (done)

**Goal:** one client that talks to OpenAI, Groq, Ollama or a deterministic offline stub, with spend tracking that **refuses** paid calls at the cap.

```text
LlmClient.chat(messages)
  offline?            → fixture / stub, $0
  cache hit?          → replay, $0
  paid provider:      pricing present? budget left? else refuse
  network call        → retry 429 / 5xx / dropped connection with backoff (+ Retry-After)
  paid                → tokens × price appended to the spend ledger
  write cache
```

**Built:** `llm/client.py`, `providers.py`, `cache.py`, `budget.py`, `retry.py`; CLI rewritten with typer; `spend` and `smoke` commands; real prices (nano $0.20 / $0.02 cached / $1.25 output per 1M; mini $0.75 / $0.075 / $4.50); `reasoning_effort = "none"`.

**Exit criteria met:** cached rerun costs $0, budget refusal is a clear non-zero exit, offline never reads the key. Pending only the one paid smoke call with the owner's key.

---

## Phase 3 — RAG bot as system under test (done)

**Goal:** three frozen bot versions over `data/corpus/`, producing immutable traces.

| Version | Retrieval | Policy |
|---|---|---|
| v1 naive | BM25 top-4 over the whole corpus, scraped docs included | answers everything, no citation rule |
| v2 guardrails | same as v1 | scope gate (no model call for out-of-scope), advice filter, unsafe-claim filter, citation enforcement |
| v3 entity-aware | named fund's official docs only (longest alias match), scraped never retrieved | v2 guardrails + entity-scoped prompt |

**Built:** `bot/` (corpus chunking + alias index, BM25 retrievers, prompts, deterministic guardrails, `run_case`), `patterns.py` (detection rules shared with graders), `runner.py`, `evalpilot run`, offline fixtures per `version:case_id`. Traces record raw and final answer, retrieved and cited docs, refusal, guardrails fired, detected entities, usage, cost, cache status.

**Exit criteria met:** 123 traces offline; v1 visibly fails, v2 guardrails catch scripted slips, v3 fixes entity confusion. Pending only one paid run.

---

## Phase 4 — Graders (4A) and Full AI System Audit (4B)

### 4A — Binary graders

**Goal:** every trace gets **8 independent pass/fail bits**, one failure mode each. These graders are also the audit's behaviour engine.

```text
Trace ──┬─► code/refusal ─┬─► code/advice ─┬─► code/unsafe_claim
        ├─► code/citation ├─► code/wrong_entity ├─► code/fee_accuracy
        ├─► llm/judge_grounded
        └─► llm/judge_helpful_compliant
                 ▼
          GradeRecord { case_id, version, grader, passed, evidence, kind }
```

- Code graders reuse `patterns.py` (the same rules the v2/v3 guardrails use), run on the **final** answer, and are unit-tested against pass/fail fixtures. Not-applicable cases return `n/a`, excluded from pass rates.
- Judges: prompts in `data/judge_prompts.md`, strict JSON `{pass, reason}`, judge model (mini) only, cached and budget-guarded; invalid JSON is `judge_parse_error`, never a pass.
- CLI: `evalpilot grade --run <id> [--graders code|llm|all] [--provider X]`.

### 4B — Full AI System Audit

**Goal:** turn EvalPilot into an audit tool for any LLM system. Full spec in `Docs/Audit.md`.

```text
Inputs ──► Intake ──┬─► Behaviour evals (4A graders over URL replies or supplied traces)
 URL + adapter      ├─► Security probes: OWASP LLM Top 10 2026 pack (canary / regex / judge)
 system card        ├─► Code scan: gitleaks · bandit · LLM-specific regex rules · AI review (file+line evidence)
 traces             └─► Config review: system card + config files
 repo / zip / path                 │
                                   ▼
                      Findings ──► Risk engine: merge by root cause,
                                   severity = likelihood × impact, evidence + fix per risk
                                   │
                                   ├─► risk_register.json
                                   ├─► coverage.json (threats × guardrail layers)
                                   ├─► verdict.json (preliminary SHIP/BLOCK)
                                   └─► audit.md
```

| Component | Responsibility |
|---|---|
| `audit/intake.py` | validate inputs; HTTP adapter; system-card schema (pydantic); traces import; safe repo/zip download + extraction |
| `audit/engines/behaviour.py` | run cases through target URL or grade supplied traces with the 4A graders |
| `audit/engines/security.py` | run `data/probes/owasp_llm_2026.jsonl` against the target with probe cap, rate limit, authorization flag |
| `audit/engines/code_scan.py` | gitleaks (or regex fallback), bandit, rule pack, AI review with evidence verification; **never executes target code** |
| `audit/engines/config_review.py` | system-card and config-file checks |
| `audit/risk.py`, `coverage.py`, `verdict.py` | merge, score, map coverage, decide |
| `audit/export_md.py` | Markdown report |
| `examples/vulnerable_bot/`, `examples/fixed_bot/` | stdlib HTTP bots with 12 planted flaws and their fixes, plus system cards, adapters, `PLANTED_FLAWS.json`, `FIXES.json` |

**Verdict rule (preliminary):** BLOCK if any open Critical or more than `max_open_high` open High risks; otherwise SHIP with conditions.

**Exit criteria:**

- 4A: all 8 graders on every trace (123 × 8 = 984 records offline); code graders fixture-tested; judges binary only.
- 4B: auditing `vulnerable_bot` finds **every** planted flaw with evidence and returns BLOCK; auditing `fixed_bot` finds **none** of them and returns SHIP; `audit-diff` shows each flaw `open → closed`. All offline, $0.
- Target code is never executed (asserted in tests); secrets are redacted in every output.

---

## Phase 5 — Human labels and calibration

**Goal:** measure the LLM components against ground truth.

```text
Trace + GradeRecord ──► label CLI ──► labels.jsonl ──► confusion matrix, TPR, TNR, Cohen's κ (per judge)
AI review findings  ──► compare with PLANTED_FLAWS.json ──► precision / recall of AI code review
```

- Human labels are the source of truth for both judges: **≥ 60 labels, ≥ 30 per judge**, target κ ≥ 0.6.
- AI code review is scored automatically against the example bots' planted flaws (ground truth already exists), plus rejected-evidence rate.
- CLI: `evalpilot label`, `evalpilot calibrate --min-labels 60`.

**Exit criteria:** both judges calibrated on 60+ labels; calibration and AI-review precision saved for the report.

---

## Phase 6 — Run compare and release gate

**Goal:** answer the PM's question with a **CI-blocking gate**.

```text
Run A (v1) vs Run B (v3) ──► per case × grader: fixed | regressed | still_pass | still_fail
                         ──► Gate(evals.toml): min pass rates, max regressions, required improvements
                         ──► exit 0 ship · exit 1 block
```

| Check | Pass condition |
|---|---|
| v1 | **fails** the gate |
| v2 vs v1 | strictly better on `refusal`, `advice`, `unsafe_claim`, `citation` |
| v3 vs v2 | better on `wrong_entity`, **no regressions** |
| v3 | **passes**, or the report states exactly which rule failed |

CI (GitHub Actions, public repo, offline only): pytest → offline run → grade → `! gate v1` → `gate v3` → offline audit of both example bots (vulnerable must BLOCK, fixed must SHIP).

**Exit criteria:** compare lists case ids; gate exit codes proven in tests and CI.

---

## Phase 7 — Report, audit export, final verdict, definition of done

**Goal:** one place where a PM (or reviewer) sees everything, and one final decision.

| Output | Contents |
|---|---|
| `docs/report.html` (single file, GitHub Pages) | spend, eval pass-rate matrix, compare tables, gate verdict, judge calibration, case explorer, **Audit section** (risk register, coverage heatmap, audit verdict) |
| `audit.md` / `audit.pdf` | executive summary, verdict with deciding risks, risk register (severity = L × I, evidence, fix, status), coverage map, evidence appendix |
| Final verdict | **SHIP only if the release gate passes AND the audit verdict is SHIP**; otherwise BLOCK naming the deciding rules/risks |
| `README.md` | 3-command quick start, results table, audit example (vulnerable → fixed) |

**Exit criteria (definition of done):** all items in `Docs/Problemstatment.md`, including the audit extension; see `Docs/Implementation-Plan.md` §7.

---

## Phase 8 — Backend API on Render

**Goal:** expose what the CLI already computes (runs, gates, compares, calibration, audits, final verdict, spend) as a
read-mostly HTTP API that the Phase 9 frontend can call. The API is a thin layer over the `evalpilot` library: no
grading or gate logic is duplicated, and every response is built by the same functions as the CLI and the HTML
report (`report.build_context`, `compare.evaluate_gate`, `audit.verdict.final_decision`).

```text
Vercel frontend ──HTTPS──► Render web service (FastAPI + uvicorn, one instance)
                              │
                              ├─ GET  read-only views ─► evalpilot library ─► runs/reference/ (baked into the deploy)
                              │                                          └─► runs/ (ephemeral, uploads only)
                              ├─ POST /api/audits ────► intake caps ─► offline engines (code never executed)
                              └─ no OpenAI key; provider forced to offline
```

| Component | Responsibility |
|---|---|
| `src/evalpilot/api/app.py` | FastAPI app factory, CORS allowlist, error handlers mapping `ConfigError`/`ValidationError`/`IntakeError` to 4xx |
| `api/app.py` routes | runs (matrix, gates, compares, calibration, paginated case explorer); audits (register, coverage, verdict, evidence, `.md`/`.pdf` export); final verdict; job submit/poll |
| `api/repository.py` | id validation, reference runs + audits (and temporary uploads), cached `build_context` per run × version |
| `api/jobs.py` | in-process queue: one offline audit at a time, bounded, uploads deleted afterwards |
| `api/settings.py` | `EVALPILOT_API_MODE` (`readonly` default), allowed origins, upload caps, rate limit, data root |
| `render.yaml` | Render Blueprint: web service, build/start commands, health check, env vars (no secrets in the file) |

| Endpoint | Method | Notes |
|---|---|---|
| `/health` | GET | liveness for the Render health check; reports version and data root |
| `/api/runs`, `/api/runs/{run_id}` | GET | reference run(s) and their summary (matrix, gates, compares, calibration, spend) |
| `/api/runs/{run_id}/cases` | GET | case explorer: query, retrieved docs, answer, 8 grades with evidence; filters + pagination |
| `/api/audits`, `/api/audits/{audit_id}` | GET | register sorted by severity, coverage map, verdict, planted flaws |
| `/api/audits/{audit_id}/export.{md,pdf}` | GET | same files as `audit-report` |
| `/api/verdict?version=v3&run=…` | GET | `FinalVerdict` JSON (deciding rules + risks) |
| `/api/audits` | POST | `mode=jobs` only; offline engines; upload size/count caps; returns a job id |
| `/api/jobs/{job_id}` | GET | `queued`/`running`/`done`/`failed` + audit id |

**Hosting constraints (Render free web service) and how the design handles them:**

| Constraint | Handling |
|---|---|
| No persistent disk; filesystem resets on every deploy/restart | reference data is part of the repo; uploaded audits are temporary and listed as such; no ledger on Render, so paid calls are impossible rather than merely budgeted |
| Spins down when idle; cold start of tens of seconds | `/health` is cheap; frontend shows a "waking the API" state and retries |
| Small instance (512 MB RAM) | one worker; uploads capped; jobs run one at a time in an in-process queue |
| Public URL | CORS allowlist = the Vercel domain(s); per-IP rate limit on POST; read-only mode by default |

**Security rules carried over from the audit spec:** the hosted API never holds `OPENAI_API_KEY` and forces
`--provider offline`; URL probing is disabled (no `--authorized` on a public service, to avoid SSRF); uploaded code is
only read, never imported or executed; zip extraction reuses `safe_extract.py`; every response passes through `redact()`.

**Exit criteria:** API tests (FastAPI `TestClient`) pass offline in CI; `render.yaml` deploys; `/health` is green on the
Render URL; `GET /api/verdict?version=v3` on Render returns the same JSON as `evalpilot verdict --run reference/<id>`.

---

## Phase 9 — Frontend on Vercel

**Goal:** an interactive web version of the Phase 7 report for PMs and reviewers, backed by the Phase 8 API and
deployed as a static site on Vercel.

```text
Browser ──► Vercel (static build, CDN) ──fetch──► Render API (Phase 8)
                     │
                     └─ snapshot.json (reference context exported at build time) ─► fallback when the API is asleep/down
```

| View | Contents |
|---|---|
| Overview | final verdict banner (gate AND audit), spend vs budget, gate per version with violation lines |
| Pass rates | 8 graders × 3 versions matrix with `n/a`, thresholds from `[gate]` |
| Compare | fixed / regressed case ids per grader for v1→v2 and v2→v3 |
| Calibration | TPR, TNR, accuracy, κ per judge; "pending labels" state |
| Case explorer | filter by category, version, failing grader, text; answer + retrieved docs + grade evidence |
| Audits | list (vulnerable BLOCK, fixed SHIP, own bot); risk register sortable by severity; coverage heatmap; evidence drill-down; Markdown/PDF download |
| Run an audit | upload traces / system card / zip → job status → result (only when the API runs in `jobs` mode) |

| Component | Responsibility |
|---|---|
| `web/` | frontend app (framework to confirm before Phase 9), TypeScript |
| `web/src/api.ts` | typed client; base URL from `VITE_API_BASE_URL` (public, not a secret); timeouts, cold-start retry |
| `web/src/types.ts` | types generated from the API's OpenAPI schema, so frontend and backend can't drift silently |
| `web/public/snapshot.json` | `report.build_context` output for `runs/reference/`, produced offline at build time |
| `vercel.json` | SPA rewrites, security headers (CSP `default-src 'self'` + the Render origin in `connect-src`) |

**Security rules:** bot answers and audit excerpts contain live XSS payloads from `vulnerable_bot`, so they render as
text only (no raw-HTML injection anywhere); no secrets in the frontend bundle; the only network origin is the Render API.

**Exit criteria:** frontend tests (unit + component) pass in CI; Vercel production build succeeds; every Phase 7 report
section is reachable; the site still shows the reference results with the API asleep (snapshot fallback); a Lighthouse
accessibility score ≥ 90.

---

## Cross-cutting architecture

### CLI command map

| Command | Phase | Side effects |
|---|---|---|
| `run` | 3 | bot calls (cached), traces on disk |
| `spend`, `smoke` | 2 | read ledger / one tiny call |
| `grade` | 4A | code graders always; judge calls if requested |
| `audit` | 4B | probes against an authorized target, static scans, optional AI review; writes `runs/audit-<id>/`; exit 0 SHIP / 1 BLOCK |
| `audit-diff` | 4B | read-only comparison of two audits |
| `audit-report --format md` | 4B | writes Markdown |
| `label`, `calibrate` | 5 | labels file / read-only metrics |
| `compare`, `gate` | 6 | read-only; exit code |
| `report`, `audit-report --format pdf`, `verdict` | 7 | writes HTML / PDF / final verdict JSON |
| `serve` | 8 | runs the API locally (`uvicorn`); same app Render starts |

### Data flow

```text
cases.jsonl + corpus/ ──► run(version) ──► traces ──► grade() ──► grades ──┬─► label/calibrate
                                                                           ├─► compare + gate
audit inputs ──► intake ──► engines ──► findings ──► risk engine ──────────┤
                                                                           ▼
                                                    report.html · audit.md · audit.pdf · final verdict
```

### Cost control

```text
Request
  ├─ provider == offline? → stub, $0
  ├─ cache hit?           → replay, $0
  ├─ spend >= budget_usd? → refuse
  └─ paid call            → tokens × price → append-only ledger, printed after every run and audit
```

### Phase dependency graph

```text
Phase 1 Skeleton
  └─► Phase 2 Provider / budget / cache
        └─► Phase 3 RAG v1/v2/v3
              └─► Phase 4A Graders
                    ├─► Phase 4B Audit (behaviour engine reuses graders)
                    ├─► Phase 5 Labels + calibration (judges; AI-review precision needs 4B)
                    └─► Phase 6 Compare + gate
                          └─► Phase 7 Report + audit export + final verdict
                                └─► Phase 8 Backend API (Render)
                                      └─► Phase 9 Frontend (Vercel)
```

Phases 5 and 6 can overlap once Phase 4 exists. Phase 7 is the last evaluation phase: reports are a **view** over traces, grades, labels, diffs, audits, spend and verdicts — never a second source of truth. Phases 8 and 9 keep that rule: the API serves the same views over HTTP and the frontend only renders them.

---

## Out of scope (until the spec says otherwise)

- Multi-turn conversation evals beyond the 41-case set (multi-turn *probes* are in scope for the audit).
- Likert / 1–5 quality scores.
- Training or fine-tuning the bot.
- Paid providers or paid scanners other than OpenAI.
- Executing, building or dynamically testing target source code.
- Probing systems the user isn't authorized to test; load or denial-of-service testing.
- Paid OpenAI calls from the hosted backend (Render runs offline only; paid runs stay on the owner's machine).
- User accounts / login (the hosted API is read-only by default; uploads are rate-limited and temporary).
- Paid hosting tiers (Render free web service and Vercel Hobby only).
- Real customer data (corpus and example bots are fictional).
