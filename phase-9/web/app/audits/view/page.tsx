"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { GuardrailPanel } from "@/components/GuardrailPanel";
import { RiskRegister } from "@/components/RiskRegister";
import { Badge, Button, ButtonLink, Card, CardTitle, LoadState, SourceBadge, StatCard, Tabs, guardrailTone, levelTone } from "@/components/ui";
import { ApiError, apiPost, exportUrl } from "@/lib/api";
import { joinList, shortDate } from "@/lib/format";
import { useAdmin, useMeta } from "@/lib/hooks";
import { ENGINE_LABELS, GUARDRAIL_LABELS, OWASP_NAMES, decisionLabel, label } from "@/lib/labels";
import type { AuditDetail, Job, Risk } from "@/lib/types";
import { useApi } from "@/lib/useApi";

const TABS = [
  { id: "overview", label: "Overview" },
  { id: "evals", label: "Evals" },
  { id: "security", label: "Security" },
  { id: "code", label: "Code" },
  { id: "risks", label: "Risks" },
  { id: "guardrails", label: "Guardrails" },
];

const TAB_SOURCES: Record<string, string[]> = {
  evals: ["Eval grader"],
  security: ["Security test"],
  code: ["Code rule", "Code scanner", "AI code review", "Config review"],
};

export default function AuditViewPage() {
  return (
    <Suspense fallback={<LoadState loading error={null}>{null}</LoadState>}>
      <AuditView />
    </Suspense>
  );
}

function AuditView() {
  const params = useSearchParams();
  const id = params.get("id");
  const { data, loading, error, reload, source } = useApi<AuditDetail>(id ? `/api/audits/${encodeURIComponent(id)}` : null);
  if (!id) {
    return (
      <Card className="p-6">
        No audit selected. <Link href="/audits/" className="text-brand underline">See all audits</Link>.
      </Card>
    );
  }
  return (
    <LoadState loading={loading || !data} error={error} onRetry={reload}>
      {data && <Report audit={data} source={source} />}
    </LoadState>
  );
}

function Report({ audit, source }: { audit: AuditDetail; source: string | null }) {
  const router = useRouter();
  const params = useSearchParams();
  const tab = TABS.some((t) => t.id === params.get("tab")) ? (params.get("tab") as string) : "risks";
  const { data: meta } = useMeta();
  const { signedIn } = useAdmin(meta);
  const [rerunError, setRerunError] = useState<string | null>(null);
  const ship = audit.verdict.decision === "SHIP";
  const s = audit.stats;

  const setTab = (next: string) => {
    const q = new URLSearchParams(params.toString());
    q.set("tab", next);
    router.replace(`/audits/view/?${q.toString()}`, { scroll: false });
  };

  const rerun = async () => {
    setRerunError(null);
    try {
      const job = await apiPost<Job>(`/api/audits/${encodeURIComponent(audit.audit_id)}/rerun`, {});
      router.push(`/audits/new/?step=5&job=${job.job_id}`);
    } catch (err) {
      setRerunError(err instanceof ApiError ? err.message : String(err));
    }
  };

  const sources = TAB_SOURCES[tab];
  const tabRisks: Risk[] = sources ? audit.risks.filter((r) => r.found_by.some((f) => sources.includes(f))) : audit.risks;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 text-sm text-muted">
            Audit · {audit.target} · {joinList(audit.input_kinds) || "no inputs recorded"} · {shortDate(audit.finished, true)} <SourceBadge source={source} />
          </div>
          <h1 className="mt-1 text-[28px] font-normal leading-tight tracking-[-0.01em]">{audit.headline}</h1>
        </div>
        <div className="flex flex-wrap gap-2">
          {signedIn && audit.rerunnable && <Button onClick={rerun}>Re-run audit</Button>}
          {audit.exports.includes("audit.md") && (
            <ButtonLink href={exportUrl(audit.audit_id, "md")} external>
              Export Markdown
            </ButtonLink>
          )}
          <ButtonLink href={exportUrl(audit.audit_id, "pdf")} variant="dark" external>
            Export PDF
          </ButtonLink>
        </div>
      </div>
      {rerunError && (
        <p role="alert" className="text-sm text-fail">
          {rerunError}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Verdict" value={decisionLabel(audit.verdict.decision)} tone={ship ? "pass" : "fail"} />
        <StatCard label="Quality" value={s.quality_pct === null ? "—" : `${s.quality_pct}%`} sub={s.behaviour_records ? `${s.behaviour_records - (s.behaviour_failed ?? 0)} of ${s.behaviour_records} checks passed` : "not run"} />
        <StatCard label="Security tests passed" value={s.security_total === null ? "—" : `${s.security_passed} / ${s.security_total}`} sub={s.security_total === null ? "needs a bot URL" : undefined} />
        <StatCard label="Code findings" value={s.code_findings ?? "—"} sub={s.files_scanned ? `${s.files_scanned} files read` : s.code_findings === null ? "needs code" : undefined} />
      </div>

      <Tabs tabs={TABS} active={tab} onChange={setTab} label="Audit sections" />

      {tab === "guardrails" ? (
        <GuardrailTable audit={audit} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[1fr_290px]">
          <div className="flex min-w-0 flex-col gap-4">
            {tab === "overview" && <Overview audit={audit} />}
            {tab === "evals" && <EngineNote audit={audit} engine="behaviour" />}
            {tab === "security" && <EngineNote audit={audit} engine="security" />}
            {tab === "code" && <EngineNote audit={audit} engine="code" />}
            {tab !== "overview" && (
              <RiskRegister
                key={tab}
                risks={tabRisks}
                title={tab === "risks" ? "Risk register" : `Risks from ${TABS.find((t) => t.id === tab)?.label.toLowerCase()}`}
                empty={audit.engines.includes(tab === "evals" ? "behaviour" : tab) || tab === "risks" ? "No risks from this engine." : "This engine didn't run for this audit."}
              />
            )}
          </div>
          <GuardrailPanel guardrails={audit.guardrails} />
        </div>
      )}
    </div>
  );
}

function Overview({ audit }: { audit: AuditDetail }) {
  const v = audit.verdict;
  const deciding = audit.risks.filter((r) => v.deciding_risks.includes(r.risk_id));
  return (
    <>
      <Card className="p-5">
        <CardTitle>Why this verdict</CardTitle>
        <ul className="mt-3 list-disc pl-5 text-sm">
          {v.reasons.length ? v.reasons.map((r) => <li key={r}>{r}</li>) : <li>No blocking risks.</li>}
        </ul>
        {deciding.length > 0 && (
          <ul className="mt-3 flex flex-col gap-2">
            {deciding.map((r) => (
              <li key={r.risk_id} className="flex items-center gap-3 text-sm">
                <Badge tone={levelTone(r.level)}>{r.level}</Badge>
                <span>{r.title}</span>
                <span className="text-xs text-muted">{r.owasp ? `${r.owasp} ${label(OWASP_NAMES, r.owasp)}` : ""}</span>
              </li>
            ))}
          </ul>
        )}
        <div className="mt-4 flex flex-wrap gap-2 text-xs">
          {Object.entries(v.counts).map(([k, n]) => (
            <Badge key={k} tone={k === "critical" || k === "high" ? (n ? "fail" : "muted") : k === "medium" ? "warn" : "muted"}>
              {n} {k}
            </Badge>
          ))}
        </div>
      </Card>
      {v.conditions.length > 0 && (
        <Card className="p-5">
          <CardTitle>Conditions (fix, or accept with an owner and expiry)</CardTitle>
          <ul className="mt-3 list-disc pl-5 text-sm text-muted">
            {v.conditions.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </Card>
      )}
      <Card className="p-5">
        <CardTitle>What ran</CardTitle>
        <ul className="mt-3 flex flex-col gap-1.5 text-sm">
          {Object.entries(ENGINE_LABELS).map(([id, e]) => (
            <li key={id} className="flex items-center gap-3">
              <Badge tone={audit.engines.includes(id) ? "pass" : "muted"}>{audit.engines.includes(id) ? "ran" : "skipped"}</Badge>
              <span>
                {e.name} <span className="text-muted">· {e.what}</span>
              </span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs text-muted">
          Provider {audit.provider ?? "—"} · OpenAI spend ${audit.spend_usd.toFixed(4)}
        </p>
        {audit.notes.length > 0 && (
          <ul className="mt-2 list-disc pl-5 text-xs text-muted">
            {audit.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
      </Card>
      {audit.flaws && (
        <Card className="p-5">
          <CardTitle right={<span className="text-xs text-muted">{audit.role === "fixed" ? "should all be closed" : "should all be found"}</span>}>
            Planted flaws
          </CardTitle>
          <ul className="mt-3 divide-y divide-line text-sm">
            {audit.flaws.map((f) => {
              const good = audit.role === "fixed" ? !f.present : f.found;
              return (
                <li key={f.id} className="flex items-center gap-3 py-2">
                  <Badge tone={good ? "pass" : "fail"}>{audit.role === "fixed" ? (f.present ? "still present" : "closed") : f.found ? "found" : "missed"}</Badge>
                  <span className="font-mono text-xs text-muted">{f.id}</span>
                  <span>{f.title}</span>
                </li>
              );
            })}
          </ul>
        </Card>
      )}
    </>
  );
}

function EngineNote({ audit, engine }: { audit: AuditDetail; engine: string }) {
  const s = audit.stats;
  const ran = audit.engines.includes(engine);
  const e = ENGINE_LABELS[engine];
  let text = `${e?.name ?? engine} didn't run: it needs ${e?.needs ?? "more inputs"}.`;
  if (ran && engine === "behaviour") text = `${s.behaviour_records ?? 0} grade checks over the test questions, ${s.behaviour_failed ?? 0} failed.`;
  if (ran && engine === "security") text = `${s.security_passed ?? 0} of ${s.security_total ?? 0} OWASP attack probes were handled safely.`;
  if (ran && engine === "code") text = `${s.files_scanned ?? 0} files read (never run), ${s.code_findings ?? 0} findings with file and line evidence.`;
  return (
    <Card className="p-4 text-sm">
      <span className="font-semibold">{e?.name}</span> <span className="text-muted">· {text}</span>
    </Card>
  );
}

function GuardrailTable({ audit }: { audit: AuditDetail }) {
  return (
    <Card className="overflow-x-auto p-5">
      <CardTitle>Guardrail coverage map</CardTitle>
      <table className="mt-3 w-full text-left text-sm">
        <thead className="text-muted">
          <tr className="border-b border-line">
            {["Guardrail", "State", "Declared", "Threats", "Evidence"].map((h) => (
              <th key={h} scope="col" className="py-2 pr-4 font-normal">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {audit.guardrails.map((g) => (
            <tr key={g.layer} className="border-b border-line align-top last:border-0">
              <td className="py-3 pr-4">{label(GUARDRAIL_LABELS, g.layer)}</td>
              <td className="py-3 pr-4">
                <Badge tone={guardrailTone(g.state)}>{g.state}</Badge>
              </td>
              <td className="py-3 pr-4">{g.declared ? "yes" : "no"}</td>
              <td className="py-3 pr-4 text-muted">{g.threats.join(", ")}</td>
              <td className="py-3 pr-4 text-xs">
                <div className="text-muted">{g.detail}</div>
                {g.failed_checks.length > 0 && <div className="mt-1 font-mono text-fail">{g.failed_checks.join(", ")}</div>}
                {g.passed_checks.length > 0 && <div className="mt-1 font-mono text-pass">{g.passed_checks.join(", ")}</div>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-3 text-xs text-muted">Present needs a passing live test or code evidence. Weak: declared but untested, or some checks fail.</p>
    </Card>
  );
}
