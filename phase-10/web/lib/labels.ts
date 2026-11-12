// Plain-language names for API ids. Unknown ids fall back to the raw id, so new graders still render.

export const GRADER_LABELS: Record<string, string> = {
  fee_accuracy: "Correct facts",
  refusal: "Refusals",
  advice: "No fund advice",
  unsafe_claim: "No unsafe claims",
  citation: "Citations",
  wrong_entity: "Right fund",
  judge_helpful_compliant: "Answers the question",
  judge_grounded: "Faithful to context",
};

// Dashboard row order (mockup 2-dashboard.png), then any grader the API adds later.
export const GRADER_ORDER = [
  "fee_accuracy",
  "refusal",
  "advice",
  "unsafe_claim",
  "citation",
  "wrong_entity",
  "judge_helpful_compliant",
  "judge_grounded",
];

export const VERSION_LABELS: Record<string, string> = {
  v1: "first demo",
  v2: "guardrails",
  v3: "entity filter",
};

export const CATEGORY_LABELS: Record<string, string> = {
  in_scope_fact: "factual",
  out_of_scope: "out of scope",
  advice_bait: "advice bait",
  injection_bait: "adversarial",
  entity_confusion: "entity confusion",
  citation_required: "citation",
  fee: "fee",
};

export const OWASP_NAMES: Record<string, string> = {
  LLM01: "Prompt injection",
  LLM02: "Sensitive information",
  LLM03: "Excessive agency",
  LLM04: "Supply chain",
  LLM05: "Data and model poisoning",
  LLM06: "Unbounded consumption",
  LLM07: "Misinformation",
  LLM08: "Hidden context exposure",
  LLM09: "Vector and embedding weaknesses",
  LLM10: "Improper output handling",
};

export const GUARDRAIL_LABELS: Record<string, string> = {
  input_scope_gate: "Refusal policy",
  injection_filter: "Prompt-injection defence",
  retrieval_source_filter: "Untrusted source filter",
  entity_scoping: "Entity scoping",
  output_advice_filter: "Advice filter",
  output_unsafe_claim_filter: "Unsafe claim filter",
  citation_enforcement: "Citation enforcement",
  output_encoding: "Output sanitisation",
  hidden_context_protection: "System prompt protection",
  secrets_management: "Secrets management",
  pii_redaction: "PII redaction in logs",
  tool_confirmation: "Tool approval",
  rate_limit_and_token_caps: "Rate limiting",
  dependency_pinning: "Dependency pinning",
};

export const ENGINE_LABELS: Record<string, { name: string; what: string; needs: string }> = {
  behaviour: { name: "Quality checks", what: "The 41 test questions, graded by 8 checks", needs: "bot URL or traces" },
  security: { name: "Security probes", what: "OWASP attack prompts against the live bot", needs: "bot URL" },
  code: { name: "Code scan", what: "Secret, rule and bandit scans; code is read, never run", needs: "code" },
  config: { name: "Config review", what: "System card and config checked against the guardrail map", needs: "system card or code" },
};

export const ROLE_LABELS: Record<string, string> = {
  bot: "Demo bot (v3)",
  vulnerable: "Vulnerable example",
  fixed: "Fixed example",
  other: "Audit",
};

export const SOURCE_LABELS: Record<string, string> = {
  reference: "reference",
  upload: "uploaded",
  local: "this machine",
};

export function label(map: Record<string, string>, id: string | null | undefined): string {
  if (!id) return "—";
  return map[id] ?? id.replaceAll("_", " ");
}

export function graderOrder(graders: string[]): string[] {
  const known = GRADER_ORDER.filter((g) => graders.includes(g));
  return [...known, ...graders.filter((g) => !GRADER_ORDER.includes(g))];
}

export function gateLabel(verdict: string, style: "card" | "table" = "card"): string {
  if (verdict === "PASS") return style === "card" ? "Ship it" : "Passed";
  return "Blocked";
}

export function decisionLabel(decision: string | null | undefined): string {
  if (decision === "SHIP") return "Ship it";
  if (decision === "BLOCK") return "Blocked";
  return "No audit";
}

export const UNTRUSTED_SOURCES = new Set(["scraped", "user"]);
