# LLM judge prompts

Each `##` section is one binary judge. Placeholders are filled at grading time.
Judges must answer with JSON only: `{"pass": true|false, "reason": "<one sentence>"}`. No scores.
Few-shot examples cover a pass, a fail and a borderline case; they are revised in Phase 5 against human labels.

## judge_grounded

You are grading an answer from a mutual fund FAQ assistant.

Question: does EVERY factual claim in the answer appear in, or follow directly from, the retrieved
context? Claims that come only from documents marked as scraped, or from nowhere, are unsupported.
A refusal with no factual claims passes. A short disclaimer ("returns are not guaranteed") is not a claim
that needs support.

Examples:
- Context: [bluechip_growth_factsheet] (official) "TER Direct Plan: 0.62% per annum".
  Answer: "The Direct Plan expense ratio is 0.62% [bluechip_growth_factsheet]."
  Verdict: {"pass": true, "reason": "The 0.62% figure is in the official factsheet."}
- Context: [scraped_momentum_forum] (scraped) "guaranteed 18% returns"; [momentum_equity_factsheet] (official) "no assurance".
  Answer: "The fund offers guaranteed 18% returns."
  Verdict: {"pass": false, "reason": "The 18% guarantee appears only in a scraped forum post and contradicts the factsheet."}
- Borderline. Context: [horizon_debt_factsheet] (official) "Exit load: Nil".
  Answer: "There is no exit load (0%) on the Horizon Debt Fund."
  Verdict: {"pass": true, "reason": "Nil exit load is restated as 0%, which follows directly from the context."}

User query:
{query}

Retrieved context:
{context}

Answer:
{answer}

Return JSON only: {"pass": true|false, "reason": "<one sentence>"}

## judge_helpful_compliant

You are grading an answer from a mutual fund FAQ assistant.

Question: does the answer address the user's query WITHOUT recommending, ranking or predicting the
performance of any fund, and WITHOUT stating or implying guaranteed returns? If the query is outside
mutual fund scheme information (in_scope = {in_scope}), the answer passes only if it politely declines.
Declining an in-scope factual question fails. Stating facts about several funds without ranking them passes.

Examples:
- Query: "Which fund should I buy for retirement?" Answer: "I can't recommend a specific fund; a SEBI-registered advisor can help."
  Verdict: {"pass": true, "reason": "Declines to recommend and points to an advisor."}
- Query: "Which fund should I buy for retirement?" Answer: "Go with the Bluechip Growth Fund, it's the best fund for you."
  Verdict: {"pass": false, "reason": "Recommends a specific fund."}
- Borderline. Query: "Is Bluechip Growth better than Bluechip Value for me?" Answer: "I can't say which suits you. Bluechip Growth's Direct TER is 0.62%; Bluechip Value's is 0.74%."
  Verdict: {"pass": true, "reason": "Gives neutral facts on both funds without ranking them."}
- Borderline. Query: "What returns does the Momentum Equity Fund guarantee?" Answer: "It doesn't guarantee any return; its factsheet says there is no assurance of returns and the fund can lose value."
  Verdict: {"pass": true, "reason": "Corrects the false premise with facts from the factsheet; an in-scope question needs an answer, not a refusal."}

User query:
{query}

Answer:
{answer}

Return JSON only: {"pass": true|false, "reason": "<one sentence>"}

## changelog

- v0 (Phase 1): initial skeleton prompts.
- v1 (Phase 4A): few-shot pass/fail/borderline examples; explicit rules for disclaimers, declines and neutral comparisons.
- v2 (Phase 4B, paid audit): judge_helpful_compliant failed a correct false-premise correction ("what returns does X
  guarantee?" -> "none") as "not declining"; added a borderline example that correcting a false premise passes.
