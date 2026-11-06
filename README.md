# EvalPilot

Evals and a full AI system audit for an LLM FAQ bot, built phase by phase. Each `phase-N/` folder is a complete,
runnable copy of the project at the end of that phase. **`phase-8/` is the latest**, and it's the one CI, Render and
GitHub Pages use.

| Folder | Contents |
|---|---|
| `Docs/` | problem statement, phase-wise architecture, implementation plan, evals / testing / guardrails specs, audit spec |
| `phase-1/` … `phase-8/` | skeleton → provider + budget → RAG bot v1/v2/v3 → graders + audit → labels + calibration → compare + gate → report + PDF + final verdict → backend API |
| `.github/workflows/ci.yml` | offline CI for `phase-8/` (no API key), plus the Pages deploy of `phase-8/docs` |
| `render.yaml` | Render Blueprint for the `phase-8/` API (free web service, readonly, keyless) |

Quick start (offline, no key, $0):

```bash
cd phase-8
pip install -e ".[dev]"
evalpilot report --reference                                              # -> docs/report.html
evalpilot verdict --version v3 --run reference/20261106T143944Z-v1-v2-v3  # exit 0 SHIP / 1 BLOCK
```

See `phase-8/README.md` for results, the audit example, the API and deployment.
