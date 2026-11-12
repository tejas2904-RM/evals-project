// The audit being set up, shared by the Home input card and the New audit wizard (this tab only).
export interface AuditDraft {
  name: string;
  url: string;
  requestBody: string;
  answerPath: string;
  cardJson: string;
  repo: string;
  engines: string[];
  aiReview: boolean;
  authorized: boolean;
}

export const DEFAULT_BODY = '{"message": "$QUESTION"}';
export const DEFAULT_ANSWER_PATH = "reply";

export const EMPTY_DRAFT: AuditDraft = {
  name: "",
  url: "",
  requestBody: DEFAULT_BODY,
  answerPath: DEFAULT_ANSWER_PATH,
  cardJson: "",
  repo: "",
  engines: ["behaviour", "security", "code", "config"],
  aiReview: true,
  authorized: false,
};

const KEY = "evalpilot.audit-draft";

export function loadDraft(): AuditDraft {
  if (typeof window === "undefined") return EMPTY_DRAFT;
  try {
    const raw = window.sessionStorage.getItem(KEY);
    return raw ? { ...EMPTY_DRAFT, ...(JSON.parse(raw) as Partial<AuditDraft>) } : EMPTY_DRAFT;
  } catch {
    return EMPTY_DRAFT;
  }
}

export function saveDraft(draft: AuditDraft): void {
  window.sessionStorage.setItem(KEY, JSON.stringify(draft));
}

export function clearDraft(): void {
  window.sessionStorage.removeItem(KEY);
}

export interface CardCheck {
  ok: boolean;
  message: string;
}

/** Client-side check of the pasted system card: valid JSON with a name; counts are what the owner declared. */
export function checkCard(text: string): CardCheck | null {
  if (!text.trim()) return null;
  let card: unknown;
  try {
    card = JSON.parse(text);
  } catch (err) {
    return { ok: false, message: `Not valid JSON: ${err instanceof Error ? err.message : String(err)}` };
  }
  if (typeof card !== "object" || card === null || Array.isArray(card)) return { ok: false, message: "The card must be a JSON object" };
  const c = card as Record<string, unknown>;
  if (typeof c.name !== "string" || !c.name.trim()) return { ok: false, message: 'Add a "name" for the bot' };
  const count = (v: unknown) => (Array.isArray(v) ? v.length : 0);
  const guardrails = Array.isArray(c.guardrails_declared)
    ? c.guardrails_declared.length
    : c.guardrails && typeof c.guardrails === "object"
      ? Object.keys(c.guardrails as object).length
      : 0;
  const tools = count(c.tools);
  const sources = count(c.data_sources);
  return {
    ok: true,
    message: `Valid · ${tools} tool${tools === 1 ? "" : "s"} · ${sources} data source${sources === 1 ? "" : "s"} · ${guardrails} guardrail${guardrails === 1 ? "" : "s"} declared`,
  };
}

export type InputKind = "url" | "card" | "code";

/** Which inputs this server accepts: admin (signed in) and hosted jobs = URL + card + code; readonly = none. */
export function allowedInputs(mode: string | undefined, signedIn: boolean): Set<InputKind> {
  if (mode === "admin" && signedIn) return new Set(["url", "card", "code"]);
  if (mode === "jobs") return new Set(["url", "card", "code"]);
  return new Set();
}
