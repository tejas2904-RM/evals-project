PROBLEM STATEMENT: EvalPilot, evals for teams shipping LLM features

CONTEXT
Teams can ship LLM features fast but can't tell if they're good. In LangChain's 2025 survey of
1,340 practitioners, 32% named quality as the top barrier to production, and only about half run
offline evals. PMs are expected to own AI quality, but eval tools are built for engineers.

PROBLEM
A PM at a startup ships an AI FAQ bot for a mutual fund house. Before each release they need to
know: did this change make the bot better or worse on the failures that matter? Wrong fees,
answering out-of-scope questions, recommending funds (a compliance risk), repeating "guaranteed
returns" injected through scraped content, and missing citations. Today they spot-check a few
chats by hand, so regressions reach users.

WHAT TO BUILD
A Python CLI that:
1. Runs a 41-case eval set (data/cases.jsonl) through a RAG bot over a fictional fund house's
   docs (data/corpus/), in three versions: v1 naive, v2 with guardrails, v3 with entity-aware retrieval.
2. Grades every answer with 8 binary pass/fail graders, one failure mode each: 6 code checks and
   2 LLM judges (prompts in data/judge_prompts.md). No 1-5 scores.
3. Lets me hand-label traces and measures each judge against my labels (confusion matrix, TPR,
   TNR, Cohen's kappa).
4. Compares runs (fixed vs regressed cases) and applies a release gate from evals.toml that exits
   non-zero in CI if a release should be blocked.
5. Produces a single-file HTML report I can host on GitHub Pages for my portfolio.

Full requirements, file layout, data formats, prompts, tests and acceptance criteria are in
@BUILD_SPEC.md. Follow it, and follow its build order (section 14).

COST CONSTRAINT: OPENAI CREDIT ONLY, EVERYTHING ELSE FREE
- I have $9.59 of OpenAI credit. The OpenAI API is the ONLY paid item; total project spend must
  stay under $5.
- Bot (system under test): gpt-5.4-nano. Judge: gpt-5.4-mini (stronger than the bot).
  Model names come from env vars, so I can switch later.
- GPT-5.x are reasoning models: don't send temperature; use max_completion_tokens and the lowest
  reasoning effort the model accepts.
- Use ONE OpenAI-compatible client with a base URL per provider (openai, groq, ollama), so I can
  fall back to the free Groq tier or local Ollama without code changes.
- Required budget guard: track tokens x price per call, print spend after every run, and refuse
  paid calls once spend hits budget_usd (3.00) in evals.toml.
- Cache every response on disk so re-running unchanged cases costs nothing. Retry 429/5xx with backoff.
- Read OPENAI_API_KEY from .env (gitignored). Never commit it.
- Must also run fully offline (--provider offline) with no key. CI (GitHub Actions, public repo)
  runs offline only and never touches the paid key.
- Open-source Python libraries only; report hosted free on GitHub Pages.

DEFINITION OF DONE
- v2 beats v1 on refusal, advice, unsafe-claim and citation graders; v3 beats v2 on wrong_entity
  with no regressions.
- v1 fails the gate; v3 passes, or the report says exactly why.
- Both judges calibrated on 60+ of my labels.
- Total OpenAI spend under $5, shown by the spend printout.
- pytest passes; README has a 3-command quick start and a results table.

Start with step 1 of the build order. Ask me before adding any dependency that isn't in the spec.

---

EXTENSION: FULL AI SYSTEM AUDIT (added after Phase 3; full spec in Docs/Audit.md)

After Phase 3, turn EvalPilot into an audit tool. Inputs: bot URL, system card JSON (or traces JSONL),
and/or a public GitHub repo or zip. Engines: behaviour evals, an OWASP LLM Top 10 (2026) security
probe pack, a code scan (gitleaks/bandit/regex rules plus AI review with file and line evidence,
code never executed), and config review. A risk engine merges everything into a risk register
(severity = likelihood x impact, each risk with evidence and a fix), a guardrail coverage map, and a
ship/block verdict, with Markdown/PDF export. Include examples/vulnerable_bot and examples/fixed_bot
to prove every planted flaw is found and then closed. Free tools only; OpenAI only for judges and
code review, within the budget guard.

Revised build order (agreed):
4. Graders (4A) + audit foundations: intake, engines, risk register, coverage map, verdict, Markdown export (4B).
5. Labelling + judge calibration (+ AI-review precision vs planted flaws).
6. Compare + gate + CI (CI also audits both example bots offline).
7. HTML report + audit PDF + final verdict (gate AND audit).

Added to the definition of done:
- Audit of examples/vulnerable_bot finds every planted flaw with evidence and returns BLOCK.
- Audit of examples/fixed_bot closes every planted flaw and returns SHIP; audit-diff shows all closed.
- Target code is never executed; URL probing only with --authorized.
- Audit spend stays inside the same budget guard; the offline audit needs no key.