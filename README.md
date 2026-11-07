# EvalPilot

Evals and a full AI system audit for an LLM FAQ bot, built phase by phase. Each `phase-N/` folder is a complete,
runnable copy of the project at the end of that phase. **`phase-9/` is the latest**, and it's the one CI, Render,
GitHub Pages and the Vercel frontend use.

| Folder | Contents |
|---|---|
| `Docs/` | problem statement, phase-wise architecture, implementation plan, evals / testing / guardrails specs, audit spec, mockups |
| `phase-1/` … `phase-9/` | skeleton → provider + budget → RAG bot v1/v2/v3 → graders + audit → labels + calibration → compare + gate → report + PDF + final verdict → backend API → Next.js frontend |
| `.github/workflows/ci.yml` | offline CI for `phase-9/` (no API key): pytest, plus a `web` job (typecheck, vitest, `next build`); Pages deploy of `phase-9/docs` |
| `render.yaml` | Render Blueprint for the `phase-9/` API (free web service, readonly, keyless) |

Quick start (offline, no key, $0):

```bash
cd phase-9
pip install -e ".[dev]"
evalpilot report --reference                                              # -> docs/report.html
evalpilot verdict --version v3 --run reference/20261106T143944Z-v1-v2-v3  # exit 0 SHIP / 1 BLOCK
cd web && npm ci && npm run dev                                           # http://localhost:3000 (needs evalpilot serve)
```

See `phase-9/README.md` for results, the audit example, the API, the web app and deployment.
