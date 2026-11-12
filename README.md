# EvalPilot

Evals and a full AI system audit for an LLM FAQ bot, built phase by phase. Each `phase-N/` folder is a complete,
runnable copy of the project at the end of that phase. **`phase-10/` is the live stack** (CI, Render, GitHub Pages,
Vercel): public hosted audits (open v1). Anyone on the site can paste a bot URL and/or a public GitHub repo and
start an audit. Accounts, credits and paywalls are later versions.

| Folder | Contents |
|---|---|
| `Docs/` | problem statement, phase-wise architecture, implementation plan, evals / testing / guardrails specs, audit spec, mockups |
| `phase-1/` … `phase-9/` | skeleton → provider + budget → RAG bot v1/v2/v3 → graders + audit → labels + calibration → compare + gate → report + PDF + final verdict → backend API → Next.js frontend (public site read-only) |
| `phase-10/` | public hosted audits: URL + GitHub from Vercel, Render `jobs` + `OPENAI_API_KEY` Secret, SSRF blocks, budget guard |
| `.github/workflows/ci.yml` | offline CI for `phase-10/` (no API key): pytest, plus a `web` job (typecheck, vitest, `next build`); Pages deploy of `phase-10/docs` |
| `render.yaml` | Render Blueprint for the `phase-10/` API (`jobs` mode; `OPENAI_API_KEY` is a dashboard Secret, never in git) |

Quick start (offline, no key, $0):

```bash
cd phase-10
pip install -e ".[dev]"
evalpilot report --reference                                              # -> docs/report.html
evalpilot verdict --version v3 --run reference/20261106T143944Z-v1-v2-v3  # exit 0 SHIP / 1 BLOCK
cd web && npm ci && npm run dev                                           # http://localhost:3000 (needs evalpilot serve)
```

See `phase-10/README.md` for the live app. After a push: set Vercel Root Directory to `phase-10/web`, and on Render
set `OPENAI_API_KEY` as a **Secret** (never on Vercel).
