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
| 8 | Backend API (FastAPI) deployed on **Render** | built (`phase-8/`) |
| 9 | Frontend web app (**Next.js + Tailwind**, screens in `Docs/mockups/`) deployed on **Vercel**, talking to the Render API | built (`phase-9/`); live at https://evals-project.vercel.app/; public site read-only |
| 10 | Public hosted audits (open v1): anyone on the Vercel site can start a URL + GitHub audit on Render | built (`phase-10/`); auth / credits / paywalls are later versions |

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
| Secrets | `OPENAI_API_KEY` from gitignored `.env` or (Phase 10) a Render dashboard Secret. Never Vercel, never git, never CI. Secrets found by the audit are redacted in every output. |
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

## Phase 9 — Frontend on Vercel (Next.js + Tailwind)

**Goal:** a product-style web app for PMs, reviewers and bot owners that answers "is this bot safe to ship?". It
covers the eval results (dashboard, cases, compare, calibration) and the audit (risk register, guardrail coverage,
new-audit wizard). It is built with **Next.js (App Router, static export) and Tailwind CSS**, deployed on Vercel and
backed by the Phase 8 API. The look is fixed by the five mockups in `Docs/mockups/`. Their names and numbers are
placeholders; real values come from the API.

```text
                 public                                               admin (owner's machine only)
Browser ──► Vercel CDN (Next.js static export)              Browser ──► next dev (localhost)
              │  HTML/JS/CSS, snapshot.json                               │
              └─fetch──► Render API (Phase 8, readonly,                   └─fetch + Bearer token──► evalpilot serve --admin
                          no key, offline)                                    (127.0.0.1, .env key, spend ledger,
              └─ snapshot.json fallback when the API is asleep/down            budget guard, --authorized URL probing)
```

| Screen (mockup) | Route | Contents |
|---|---|---|
| Home (`1-home.png`) | `/` | dark hero "Is your AI chatbot safe to ship?" with the OWASP Top 10 for LLM Apps 2026 badge; input card with Bot URL / System card JSON / GitHub repo tiles, endpoint field, permission checkbox, input count + cost estimate, "Start audit"; 3-step explainer; demo-audit and playground cards; admin recent-audit card |
| Dashboard (`2-dashboard.png`) | `/dashboard` | per-version cards (passed / 41, critical failures, regressions, gate badge); pass rate by failure mode as paired v1/v3 bars for all 8 graders; open risks, judges trusted, OpenAI spend vs cap; recent runs table; export report and case study links |
| Audit report (`3-audit-report.png`) | `/audits/view?id=` | verdict headline; stat cards (verdict, quality, security tests passed, code findings); tabs Overview · Evals · Security · Code · Risks · Guardrails; risk register with severity/OWASP filters and expandable evidence, score and fix; guardrail coverage Present / Weak / Missing |
| New audit wizard (`4-new-audit-wizard.png`) | `/audits/new` | 5 steps Name → Inputs → Engines → Permission → Run; bot URL with request template, answer path and connection test; system card paste/upload/draft with live validation; GitHub repo or zip (read only, never run); cost estimate vs remaining cap; live job progress |
| Case explorer (`5-case-explorer.png`) | `/cases?run=&case=` | search, All / Failed / Passed / Critical chips, failing-check filter; list + detail with question, answer, checks with evidence, retrieved documents (untrusted ones flagged); label, compare with v3, copy link |
| Audits, Compare, Calibration, Playground, Admin | `/audits`, `/compare`, `/calibration`, `/playground`, `/admin` | same components: audit list; fixed/regressed ids per grader; TPR/TNR/accuracy/κ per judge with "needs N more labels"; one question to two versions side by side; how to start admin mode |

| Component | Responsibility |
|---|---|
| `web/app/` | one route folder per screen; client components fetch from the API (no server-side data fetching) |
| `web/components/ui/` | UI kit from the mockups: Badge, Card, StatCard, Button, Tabs, Stepper, PairedBar, Table, Chip, ApiStatus |
| `web/app/globals.css` | Tailwind v4 `@theme` tokens: ink nav/hero, light grey page, white cards, dark-green brand, pass/fail/warn/muted badge colours; Space Grotesk headings, Inter body |
| `web/lib/api.ts` | typed client; base URL from `NEXT_PUBLIC_API_BASE_URL` (public, not a secret); timeouts, cold-start retry, admin bearer token |
| `web/lib/types.ts` | hand-written API types; `test/contract.test.ts` type-checks them against `public/snapshot.json` |
| `web/lib/labels.ts` | plain-language names for grader ids, versions, gate and coverage states |
| `web/public/snapshot.json` | `evalpilot snapshot`: read-only API responses for `runs/reference/`, keyed by request path |
| `web/vercel.json` + `scripts/csp-hashes.mjs` | static security headers; per-page CSP meta with hashed inline scripts and the API origin in `connect-src` |
| API additions (`src/evalpilot/api/`) | the fields and routes the screens need: per-version pass/critical/regression counts, audit stat cards and guardrail states, cost estimate, job progress, playground; admin-only connection test, system-card draft, URL/repo audits, labels |

**Public vs admin.** The public site (Vercel → Render) is read-only and keyless. It shows every result and lets
visitors explore the demo audit and the reference playground answers. Live bot-URL audits, GitHub repo fetches, AI
review, paid playground answers, labelling and re-runs need the OpenAI key, the spend ledger or URL probing, so they
only exist in admin mode. Admin mode means the local frontend talking to `evalpilot serve --admin` on `127.0.0.1`. It
refuses to start when hosted and prints a per-process token. The public UI keeps these controls visible where the
mockups show them, disabled with a one-line reason.

**Security rules:** bot answers and audit excerpts contain live XSS payloads from `vulnerable_bot`, so they render as
text only. `dangerouslySetInnerHTML` is banned by a Vitest source scan (ESLint was not an approved dependency). There
are no secrets in the bundle; `NEXT_PUBLIC_*` values are public by design. The only network origin is the configured
API. The CSP has no `'unsafe-inline'` or `'unsafe-eval'` for scripts.

**Exit criteria:** frontend tests (Vitest + Testing Library) pass in CI along with the Python API tests; the Next.js
static build and CSP hash step succeed; the Vercel production site matches the five mockups and reaches every Phase 7
report section; the site still shows the reference results with the API asleep (snapshot fallback); Lighthouse
accessibility ≥ 90; admin mode works locally and stays impossible on the hosted stack.

---

## Phase 10 — Public hosted audits (open v1)

**Goal:** the published Vercel site can start real audits. Anyone can paste a bot URL and/or a public GitHub repo.
Render runs the engines (including paid OpenAI under `budget_usd`). No local admin server. No user accounts in this
phase — that is v2/v3 (purchase / subscription in front of the same POST).

Copy `phase-9/` → `phase-10/`. After the done-check, CI, Render `rootDir` and Vercel Root Directory point at `phase-10/`.

```text
Browser ──► Vercel CDN (phase-10/web static export)
              │
              ├─ GET  ──► Render API (demo dashboard, snapshot fallback if asleep)
              └─ POST /api/audits ──► Render jobs (OPENAI_API_KEY as dashboard Secret)
                                        ├─ HTTPS URL + permission tick (SSRF denylist)
                                        ├─ public GitHub archive zip
                                        └─ BudgetGuard · rate limit · one job · ephemeral disk
```

| Component | Change from Phase 9 |
|---|---|
| `api/settings.py` | Hosted `jobs` may start with `OPENAI_API_KEY`. Hosted `readonly` + key still refused. Admin still refused when hosted |
| `api/jobs.py` | If a key is present, use the live runner (URL, repo, optional AI review). If not, keep the offline hosted runner |
| `api/app.py` | `target_url` and `repo` no longer admin-only in `jobs` mode |
| `audit/intake.py` / adapters | Hosted: HTTPS only; block loopback, private, and cloud-metadata IPs |
| `web/lib/draft.ts` | `jobs` mode allows url + card + code |
| Home / wizard | Start audit enabled for visitors when `jobs_enabled` |
| `render.yaml` | `EVALPILOT_API_MODE=jobs`; `OPENAI_API_KEY` set in the dashboard (`sync: false`) |

**What stays local-admin in Phase 10:** writing `data/labels.jsonl`, free-text playground (paid live answers), re-run
of reference audits. Public visitors only create new audits.

**What v2 / v3 add later (not this phase):** sign-in, credits, Stripe / subscription, private audits, per-user quotas.
They wrap `POST /api/audits`; they do not replace the engines.

**Exit criteria:** docs + `phase-10/` folder exist; then code: public POST with URL/repo works in jobs mode; private
IPs 400; CI still keyless; after switch-over, https://evals-project.vercel.app/ can start an audit without Admin sign in.

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
| `serve --admin`, `snapshot` | 9 | admin API on 127.0.0.1 with the owner's key and budget guard (refused when hosted) / read-only API dump for the frontend fallback |
| hosted `POST /api/audits` with URL + repo | 10 | public jobs on Render; key is a Render Secret; SSRF denylist; budget guard |

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
                                            └─► Phase 10 Public hosted audits (open v1)
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
- Paid OpenAI calls from the hosted backend **in Phases 8–9** (those phases stay keyless). Phase 10 allows a Render
  Secret key for public jobs under `budget_usd`.
- User accounts / login / purchase / subscription (Phase 10 is open v1: anyone can start an audit). Planned for v2/v3
  in front of the same `POST /api/audits`. Phase 9 "Admin sign in" remains a local per-process token for labels.
- Paid hosting tiers (Render free web service and Vercel Hobby only).
- Real customer data (corpus and example bots are fictional).
