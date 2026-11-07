"use client";

import Link from "next/link";
import { Badge, ButtonLink, Card, CardTitle, LoadState, PageHeader, PairedBar, SourceBadge, cx } from "@/components/ui";
import { REPO_URL, REPORT_URL } from "@/lib/api";
import { pct, plural, shortDate, usd } from "@/lib/format";
import { useMeta, useRun } from "@/lib/hooks";
import { GRADER_LABELS, VERSION_LABELS, gateLabel, graderOrder, label } from "@/lib/labels";
import type { AuditBrief, RunSummary } from "@/lib/types";

export default function DashboardPage() {
  const meta = useMeta();
  const run = useRun(meta.data);
  const error = meta.error ?? run.error;
  return (
    <LoadState loading={meta.loading || run.loading || !run.data} error={error} onRetry={run.reload}>
      {run.data && meta.data && <Dashboard run={run.data} botName={meta.data.bots[0]?.name ?? "Demo bot"} source={run.source} />}
    </LoadState>
  );
}

function Dashboard({ run, botName, source }: { run: RunSummary; botName: string; source: string | null }) {
  const versions = run.versions;
  const first = versions[0] ?? "v1";
  const last = versions[versions.length - 1] ?? "v3";
  const botAudit = run.audits.find((a) => a.role === "bot");
  const trusted = run.judges_trusted.filter((j) => j.trusted).length;
  const untrusted = run.judges_trusted.filter((j) => !j.trusted);
  const spend = run.spend;

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow={
          <span className="flex items-center gap-2">
            {botName.replace(" (demo)", "")} · latest run {shortDate(run.meta.as_of, true)} · {run.meta.n_cases} test questions <SourceBadge source={source} />
          </span>
        }
        title="Is this bot safe to ship?"
        right={
          <>
            <ButtonLink href={REPORT_URL} external>
              Export report
            </ButtonLink>
            <ButtonLink href={`${REPO_URL}#readme`} external>
              Read the case study
            </ButtonLink>
          </>
        }
      />

      <div className="grid gap-4 md:grid-cols-3">
        {versions.map((v) => {
          const s = run.version_summaries[v];
          if (!s) return null;
          const passed = s.gate === "PASS";
          const parts = [plural(s.critical_failures, "critical failure")];
          if (s.regressed_cases.length) parts.push(plural(s.regressed_cases.length, "regression"));
          return (
            <Card key={v} className="p-5" aria-label={`${v} summary`}>
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted">
                  {v} · {label(VERSION_LABELS, v)}
                </span>
                <Badge tone={passed ? "pass" : "fail"}>{gateLabel(s.gate)}</Badge>
              </div>
              <div className="mt-3 font-display text-[34px] font-semibold leading-none">
                {s.cases_passed} / {s.cases_total}
              </div>
              <div className="mt-2 text-sm text-muted">{parts.join(" · ")}</div>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_250px]">
        <Card className="p-5">
          <CardTitle right={<span className="text-xs text-muted">Grey {first} · Green {last}</span>}>Pass rate by failure mode</CardTitle>
          <ul className="mt-5 flex flex-col gap-4">
            {graderOrder(run.graders).map((g) => {
              const a = run.matrix[g]?.[first]?.rate ?? null;
              const b = run.matrix[g]?.[last]?.rate ?? null;
              return (
                <li key={g} className="grid grid-cols-[110px_1fr_104px] items-center gap-3 text-sm sm:grid-cols-[150px_1fr_112px] sm:gap-4">
                  <span title={g}>{label(GRADER_LABELS, g)}</span>
                  <PairedBar a={a} b={b} labelA={`${first} ${label(GRADER_LABELS, g)}`} labelB={`${last} ${label(GRADER_LABELS, g)}`} />
                  <span className="whitespace-nowrap text-right tabular-nums text-muted">
                    {pct(a)} → {pct(b)}
                  </span>
                </li>
              );
            })}
          </ul>
        </Card>

        <div className="flex flex-col gap-4">
          <OpenRisks audit={botAudit} />
          <Card className="p-4">
            <h2 className="text-[15px] font-semibold">Judges trusted</h2>
            <div className="mt-2 font-display text-[28px] font-semibold leading-none">
              {trusted} of {run.judges_trusted.length}
            </div>
            <p className="mt-2 text-xs text-muted">
              {untrusted.length === 0
                ? "Both judges agree with human labels"
                : untrusted.map((j) => `${label(GRADER_LABELS, j.judge).toLowerCase()} needs ${j.labels_needed} more labels`).join("; ")}
            </p>
            <Link href="/calibration/" className="mt-1 inline-block text-xs text-brand underline">
              Calibration
            </Link>
          </Card>
          <Card className="p-4">
            <h2 className="text-[15px] font-semibold">OpenAI spend</h2>
            <div className="mt-2 flex items-baseline gap-2">
              <span className="font-display text-[28px] font-semibold leading-none">{usd(spend.total_usd)}</span>
              <span className="text-xs text-muted">of {usd(spend.budget_usd)} cap</span>
            </div>
            <div className="mt-3 h-2 rounded-full bg-neutral-soft" role="img" aria-label={`${pct(spend.total_usd / spend.budget_usd)} of the budget used`}>
              <div className="h-2 rounded-full bg-brand" style={{ width: `${Math.min(100, (spend.total_usd / spend.budget_usd) * 100)}%` }} />
            </div>
            <p className="mt-2 text-xs text-muted">{spend.calls} paid calls · hard ceiling {usd(spend.hard_ceiling_usd)}</p>
          </Card>
        </div>
      </div>

      <Card className="p-5">
        <CardTitle>Recent runs</CardTitle>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr className="border-b border-line">
                {["Run", "Bot", "Passed", "Fixed / regressed", "Gate", "Bot cost"].map((h) => (
                  <th key={h} scope="col" className="py-2 pr-4 font-normal">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {[...versions].reverse().map((v) => {
                const s = run.version_summaries[v];
                if (!s) return null;
                return (
                  <tr key={v} className="border-b border-line last:border-0">
                    <td className="py-3 pr-4">
                      <Link href={`/cases/?version=${v}`} className="text-brand underline">
                        {v}-{run.meta.provider}
                      </Link>
                    </td>
                    <td className="py-3 pr-4">{botName.split(" ")[0]}</td>
                    <td className="py-3 pr-4 tabular-nums">
                      {s.cases_passed} / {s.cases_total}
                    </td>
                    <td className="py-3 pr-4 tabular-nums">{s.baseline ? `+${s.fixed_cases.length} / ${s.regressed_cases.length}` : "baseline"}</td>
                    <td className="py-3 pr-4">
                      <Badge tone={s.gate === "PASS" ? "pass" : "fail"}>{gateLabel(s.gate, "table")}</Badge>
                    </td>
                    <td className="py-3 pr-4 tabular-nums">{usd(s.bot_cost_usd, 4)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-muted">
          Bot cost is what this run paid for answers ({run.legend.cache_hits} of {run.legend.traces} came from the cache). Judge and audit calls are
          in the spend total.
        </p>
      </Card>

      <ReleaseDecision run={run} />
    </div>
  );
}

function OpenRisks({ audit }: { audit: AuditBrief | undefined }) {
  return (
    <Card className="p-4">
      <h2 className="text-[15px] font-semibold">Open risks</h2>
      {audit ? (
        <>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {audit.counts.critical > 0 && <Badge tone="fail">{audit.counts.critical} critical</Badge>}
            <Badge tone="fail">{audit.counts.high} high</Badge>
            <Badge tone="warn">{audit.counts.medium} medium</Badge>
            <Badge tone="muted">{audit.counts.low} low</Badge>
          </div>
          <Link href={`/audits/view/?id=${audit.audit_id}&tab=risks`} className="mt-2 inline-block text-xs text-brand underline">
            View risk register
          </Link>
        </>
      ) : (
        <p className="mt-2 text-xs text-muted">No audit of this run yet.</p>
      )}
    </Card>
  );
}

function ReleaseDecision({ run }: { run: RunSummary }) {
  const final = run.final;
  const ship = final.decision === "SHIP";
  return (
    <Card className="p-5" aria-label="Release decision">
      <CardTitle right={<Badge tone={ship ? "pass" : "fail"}>{ship ? "Ship it" : "Blocked"}</Badge>}>
        Release decision for {final.version}: release gate and audit
      </CardTitle>
      <ul className="mt-3 list-disc pl-5 text-sm">
        {final.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <details className="mt-4">
        <summary className="cursor-pointer text-sm font-medium">Gate violations per version</summary>
        <div className="mt-2 flex flex-col gap-3">
          {run.versions.map((v) => {
            const gate = run.gates[v];
            if (!gate) return null;
            return (
              <div key={v} className="text-sm">
                <div className="font-medium">
                  {v}: {gate.verdict}
                  {gate.baseline ? ` (vs ${gate.baseline})` : ""}
                </div>
                {gate.violations.length === 0 ? (
                  <div className="text-muted">No violations.</div>
                ) : (
                  <ul className="list-disc pl-5 text-muted">
                    {gate.violations.map((x) => (
                      <li key={`${x.grader}-${x.rule}`}>
                        {label(GRADER_LABELS, x.grader)} ({x.grader}) {x.rule}: needs {x.threshold}, got {x.observed}. Cases:{" "}
                        {x.case_ids.map((id, i) => (
                          <span key={id}>
                            {i > 0 && ", "}
                            <Link className="text-brand underline" href={`/cases/?version=${v}&case=${id}`}>
                              {id}
                            </Link>
                          </span>
                        ))}
                      </li>
                    ))}
                  </ul>
                )}
                {gate.warnings.map((w) => (
                  <div key={w} className="text-xs text-warn">
                    {w}
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </details>
      <details className="mt-3">
        <summary className="cursor-pointer text-sm font-medium">Definition of done</summary>
        <ul className="mt-2 flex flex-col gap-2 text-sm">
          {run.dod.map((d) => (
            <li key={d.item} className="flex items-start gap-3">
              <Badge tone={d.status === "pass" ? "pass" : d.status === "fail" ? "fail" : "warn"} className="mt-0.5 w-20 justify-center">
                {d.status}
              </Badge>
              <span>
                <span className="block">{d.item}</span>
                <span className={cx("block text-xs text-muted")}>{d.evidence}</span>
              </span>
            </li>
          ))}
        </ul>
      </details>
    </Card>
  );
}
