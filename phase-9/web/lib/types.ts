// Shapes of the EvalPilot API responses (src/evalpilot/api/). test/contract.test.ts type-checks these against
// web/public/snapshot.json, which `evalpilot snapshot` writes from the live app, so a renamed field fails CI.
// Enum-like fields are `string` because JSON imports widen literals; lib/labels.ts maps them for display.

export type Version = string; // "v1" | "v2" | "v3"
export type GateVerdict = string; // "PASS" | "BLOCKED"
export type Decision = string; // "SHIP" | "BLOCK"

export interface Budget {
  budget_usd: number;
  spent_usd: number;
  remaining_usd: number;
}

export interface Meta {
  version: string;
  mode: string; // "readonly" | "jobs" | "admin"
  admin: boolean;
  hosted: boolean;
  jobs_enabled: boolean;
  provider: string;
  max_upload_mb: number;
  versions: Version[];
  graders: string[];
  judges: string[];
  engines: string[];
  runs: string[];
  bots: { run_id: string; name: string }[];
  budget: Budget;
}

export interface RunListItem {
  run_id: string;
  provider: string | null;
  bot_model: string | null;
  versions: Version[];
  finished: string | null;
  n_traces: number | null;
}

export interface PassRate {
  passed: number;
  applicable: number;
  na: number;
  rate: number | null;
}

export interface GateViolation {
  grader: string;
  rule: string;
  threshold: string;
  observed: string;
  case_ids: string[];
}

export interface Gate {
  version: Version;
  baseline: Version | null;
  verdict: GateVerdict;
  violations: GateViolation[];
  pass_rates: Record<string, PassRate & { failing: string[] }>;
  warnings: string[];
}

export interface GraderDiff {
  grader: string;
  counts: Record<string, number>;
  fixed: string[];
  regressed: string[];
  still_pass: string[];
  still_fail: string[];
  not_comparable: string[];
}

export interface Compare {
  baseline: Version;
  candidate: Version;
  graders: Record<string, GraderDiff>;
}

export interface GraderCalibration {
  grader: string;
  kind: string;
  n_labels: number;
  min_labels: number;
  confusion: Record<string, number>;
  tpr: number | null;
  tnr: number | null;
  accuracy: number | null;
  kappa: number | null;
  enough_labels: boolean;
  meets_targets: boolean;
  disagreements: { case_id: string; version: string; grader_pass: boolean; human_pass: boolean; evidence: string }[];
  unmatched_labels: number;
}

export interface Calibration {
  run_id: string;
  positive_class: string;
  targets: { tpr: number; tnr: number; kappa: number };
  min_labels: number;
  judge_labels: number;
  enough_labels: boolean;
  problems: string[];
  graders: Record<string, GraderCalibration>;
}

export interface FinalVerdict {
  version: Version;
  run_id: string;
  audit_id: string | null;
  gate_verdict: GateVerdict;
  audit_decision: Decision | null;
  decision: Decision;
  reasons: string[];
  deciding_rules: string[];
  deciding_risks: string[];
  conditions: string[];
}

export interface Spend {
  total_usd: number;
  budget_usd: number;
  hard_ceiling_usd: number;
  calls: number;
  by_model: Record<string, { calls: number; cost_usd: number }>;
  by_purpose: Record<string, { calls: number; cost_usd: number }>;
  last_ts: string | null;
  judge_models: string[];
}

export interface DodRow {
  item: string;
  status: string; // "pass" | "fail" | "pending" | "explained"
  evidence: string;
}

export interface VerdictCounts {
  critical: number;
  high: number;
  medium: number;
  low: number;
  accepted: number;
}

export interface AuditBrief {
  audit_id: string;
  role: string; // "bot" | "vulnerable" | "fixed" | "other"
  source: string; // "reference" | "upload" | "local"
  target: string;
  finished: string | null;
  provider: string | null;
  decision: Decision;
  counts: VerdictCounts;
  n_risks: number;
  exports: string[];
}

export interface VersionSummary {
  version: Version;
  cases_total: number;
  cases_passed: number;
  critical_failures: number;
  critical_case_ids: string[];
  baseline: Version | null;
  fixed_cases: string[];
  regressed_cases: string[];
  gate: GateVerdict;
  bot_cost_usd: number;
}

export interface JudgeTrust {
  judge: string;
  trusted: boolean;
  n_labels: number;
  min_labels: number;
  labels_needed: number;
  kappa: number | null;
}

export interface RunSummary {
  meta: {
    evalpilot_version: string;
    run_id: string;
    provider: string;
    bot_model: string;
    judge_model: string;
    n_cases: number;
    as_of: string;
  };
  versions: Version[];
  graders: string[];
  judges: string[];
  matrix: Record<string, Record<Version, PassRate>>;
  gates: Record<Version, Gate>;
  compares: Compare[];
  calibration: Calibration;
  legend: { cache_hits: number; traces: number; judge_parse_errors: number };
  audits: AuditBrief[];
  final: FinalVerdict;
  spend: Spend;
  dod: DodRow[];
  version_summaries: Record<Version, VersionSummary>;
  critical_graders: string[];
  judges_trusted: JudgeTrust[];
  documents: Record<string, { title: string; source: string }>;
}

export interface Grade {
  passed: boolean;
  na: boolean;
  evidence: string;
}

export interface CaseStatus {
  passed: boolean;
  failing: string[];
  critical: boolean;
}

export interface CaseAnswer {
  answer: string;
  citations: string[];
  retrieved: string[];
  refused: boolean;
  guardrails: string[];
  cached: boolean;
  grades: Record<string, Grade>;
  status?: CaseStatus;
}

export interface CaseItem {
  id: string;
  category: string;
  query: string;
  in_scope: boolean;
  should_refuse: boolean;
  versions: Record<Version, CaseAnswer>;
}

export interface CasePage {
  total: number;
  offset: number;
  limit: number;
  status_version: Version;
  counts: { all: number; passed: number; failed: number; critical: number };
  items: CaseItem[];
}

export interface Evidence {
  kind: string;
  location: string;
  excerpt: string;
}

export interface Risk {
  risk_id: string;
  owasp: string | null;
  title: string;
  findings: string[];
  check_ids: string[];
  evidence: Evidence[];
  likelihood: number;
  impact: number;
  severity: number;
  level: string; // "critical" | "high" | "medium" | "low"
  fix: string;
  status: string; // "open" | "closed" | "accepted"
  acceptance: Record<string, string> | null;
  capped_from: string | null;
  found_by: string[];
}

export interface CoverageCell {
  layer: string;
  threats: string[];
  declared: boolean;
  status: string;
  passed_checks: string[];
  failed_checks: string[];
}

export interface Guardrail {
  layer: string;
  state: string; // "present" | "weak" | "missing" | "n/a"
  detail: string;
  threats: string[];
  declared: boolean;
  passed_checks: string[];
  failed_checks: string[];
}

export interface PlantedFlaw {
  id: string;
  title: string;
  owasp: string | null;
  found: boolean;
  present: boolean;
  matched_checks: string[];
}

export interface AuditStats {
  quality_pct: number | null;
  behaviour_records: number | null;
  behaviour_failed: number | null;
  security_passed: number | null;
  security_total: number | null;
  code_findings: number | null;
  files_scanned: number | null;
}

export interface AuditDetail {
  audit_id: string;
  role: string;
  source: string;
  target: string;
  provider: string | null;
  finished: string | null;
  engines: string[];
  spend_usd: number;
  verdict: { decision: Decision; deciding_risks: string[]; reasons: string[]; conditions: string[]; counts: VerdictCounts };
  risks: Risk[];
  coverage: CoverageCell[];
  flaws: PlantedFlaw[] | null;
  exports: string[];
  notes: string[];
  headline: string;
  stats: AuditStats;
  guardrails: Guardrail[];
  input_kinds: string[];
  rerunnable: boolean;
}

export interface Estimate {
  provider: string;
  paid: boolean;
  per_engine: Record<string, number>;
  calls: Record<string, number>;
  total_usd: number;
  spent_usd: number;
  budget_usd: number;
  remaining_usd: number;
  fits_budget: boolean;
}

export interface Job {
  job_id: string;
  name: string;
  status: string; // "queued" | "running" | "done" | "failed"
  created: string;
  finished: string | null;
  audit_id: string | null;
  decision: Decision | null;
  error: string | null;
  progress: Record<string, string>;
  notes: string[];
}

export interface ConnectionTest {
  ok: boolean;
  status: number;
  sample_reply: string;
  latency_s: number;
  error: string;
}

export interface CardDraft {
  card: Record<string, unknown>;
  notes: string[];
  files_read: number;
}

export interface PlaygroundAnswer {
  source: string;
  query: string;
  answers: Record<Version, CaseAnswer>;
  cost_usd: number;
}

export interface Snapshot {
  format: number;
  evalpilot_version: string;
  as_of: string;
  responses: Record<string, unknown>;
}
