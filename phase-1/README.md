# EvalPilot — Phase 1: skeleton, config, data contracts

Phase 1 of the build described in `../Docs/Implementation-Plan.md` and `../Docs/Phase-wise-Architecture.md`.
No model is called in this phase; cost is **$0**.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env            # Windows: copy .env.example .env
evalpilot run --dry-run --provider offline
pytest
```

`python -m evalpilot ...` works too, without installing.

## What's here

| Path | Purpose |
|---|---|
| `evals.toml` | budget (`budget_usd = 3.00`), model env-var names, GPT-5.x params, providers, pricing (fill before paid calls) |
| `.env.example` | model names and keys; copy to gitignored `.env` |
| `data/cases.jsonl` | 41 eval cases across 7 categories |
| `data/corpus/` | 11 docs for the fictional **Asterion Mutual Fund**: 7 fund factsheets, 2 service docs, 2 scraped docs with injected "guaranteed returns" claims |
| `data/judge_prompts.md` | skeleton prompts for the two binary LLM judges |
| `src/evalpilot/models.py` | `Case`, `Doc`, `Trace`, `GradeRecord`, `Label` with validation |
| `src/evalpilot/config.py` | loads `evals.toml` + `.env`; offline never reads a key |
| `src/evalpilot/data.py` | case/corpus loaders, alias map, cross-reference checks |
| `src/evalpilot/store.py` | run ids and JSONL persistence |
| `src/evalpilot/cli.py` | `evalpilot` CLI; `run --dry-run` works, other commands name the phase that implements them |

## Case distribution

| Category | Count |
|---|---|
| in_scope_fact | 8 |
| fee | 7 |
| out_of_scope | 7 |
| advice_bait | 6 |
| injection_bait | 5 |
| entity_confusion | 5 |
| citation_required | 3 |

## Deviations from the plan

The plan lists `pydantic`, `typer` and `python-dotenv`. The problem statement says to ask before adding
dependencies not in the spec, so Phase 1 uses only the standard library (`dataclasses`, `argparse`,
`tomllib`, a small `.env` reader). Runtime dependencies: none. Dev: `pytest`.

## Done-check

- [x] `pytest` green
- [x] `evalpilot --help` lists all commands
- [x] `.env` gitignored; offline needs no key
- [x] 41 cases + corpus with cross-reference validation

## Revised build plan

The plan now adds a full AI system audit (see `../Docs/Audit.md`). Phase 4 = 4A graders + 4B audit
(intake, behaviour evals, OWASP LLM Top 10 2026 probes, code scan, config review, risk register,
coverage map, ship/block verdict, Markdown export, `examples/vulnerable_bot` and `examples/fixed_bot`).
Then 5 calibration, 6 compare + gate + CI, 7 HTML report + audit PDF + final verdict. The `audit`,
`audit-diff` and `audit-report` commands are stubs here that point to Phase 4.
