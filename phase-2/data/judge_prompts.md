# LLM judge prompts

Each `##` section is one binary judge. Placeholders are filled at grading time.
Judges must answer with JSON only: `{"pass": true|false, "reason": "<one sentence>"}`. No scores.
Few-shot examples are added and tuned in Phase 4/5.

## judge_grounded

You are grading an answer from a mutual fund FAQ assistant.

Question: does EVERY factual claim in the answer appear in, or follow directly from, the retrieved
context? Claims that come only from documents marked as scraped, or from nowhere, are unsupported.
A refusal with no factual claims passes.

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

User query:
{query}

Answer:
{answer}

Return JSON only: {"pass": true|false, "reason": "<one sentence>"}

## changelog

- v0 (Phase 1): initial skeleton prompts.
