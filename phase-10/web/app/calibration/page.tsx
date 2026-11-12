"use client";

import Link from "next/link";
import { Badge, Card, CardTitle, LoadState, PageHeader, SourceBadge } from "@/components/ui";
import { pct } from "@/lib/format";
import { useMeta, useRun } from "@/lib/hooks";
import { GRADER_LABELS, graderOrder, label } from "@/lib/labels";
import type { GraderCalibration } from "@/lib/types";

function kappa(v: number | null): string {
  return v === null ? "—" : v.toFixed(2);
}

export default function CalibrationPage() {
  const meta = useMeta();
  const run = useRun(meta.data);
  const cal = run.data?.calibration;
  const judges = run.data?.judges ?? [];
  const code = cal ? graderOrder(Object.keys(cal.graders)).filter((g) => !judges.includes(g)) : [];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow={<span className="flex items-center gap-2">Do the LLM judges agree with a human? Positive class = pass <SourceBadge source={run.source} /></span>}
        title="Judge calibration"
      />
      <LoadState loading={meta.loading || run.loading || !cal} error={meta.error ?? run.error} onRetry={run.reload}>
        {cal && (
          <>
            <div className="grid gap-4 md:grid-cols-2">
              {judges.map((j) => {
                const g = cal.graders[j];
                return g ? <JudgeCard key={j} g={g} targets={cal.targets} /> : null;
              })}
            </div>
            <Card className="p-5">
              <CardTitle right={<Badge tone={cal.enough_labels ? "pass" : "warn"}>{cal.enough_labels ? "enough labels" : "labels pending"}</Badge>}>
                {cal.judge_labels} of {cal.min_labels} judge labels
              </CardTitle>
              {cal.problems.length > 0 && (
                <ul className="mt-3 list-disc pl-5 text-sm text-muted">
                  {cal.problems.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              )}
              <p className="mt-3 text-sm text-muted">
                Labels are the owner&apos;s judgement of real answers. In admin mode, use &quot;Label this answer&quot; in the{" "}
                <Link href="/cases/" className="text-brand underline">
                  case explorer
                </Link>
                , or run <code className="font-mono">evalpilot label</code>.
              </p>
            </Card>
            {code.length > 0 && (
              <Card className="overflow-x-auto p-5">
                <CardTitle>Code checks (sanity check only, not gated)</CardTitle>
                <table className="mt-3 w-full text-left text-sm">
                  <thead className="text-muted">
                    <tr className="border-b border-line">
                      {["Check", "Labels", "TPR", "TNR", "Accuracy", "κ"].map((h) => (
                        <th key={h} scope="col" className="py-2 pr-4 font-normal">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {code.map((name) => {
                      const g = cal.graders[name] as GraderCalibration;
                      return (
                        <tr key={name} className="border-b border-line last:border-0">
                          <td className="py-2 pr-4">{label(GRADER_LABELS, name)}</td>
                          <td className="py-2 pr-4 tabular-nums">{g.n_labels}</td>
                          <td className="py-2 pr-4 tabular-nums">{pct(g.tpr)}</td>
                          <td className="py-2 pr-4 tabular-nums">{pct(g.tnr)}</td>
                          <td className="py-2 pr-4 tabular-nums">{pct(g.accuracy)}</td>
                          <td className="py-2 pr-4 tabular-nums">{kappa(g.kappa)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Card>
            )}
          </>
        )}
      </LoadState>
    </div>
  );
}

function JudgeCard({ g, targets }: { g: GraderCalibration; targets: { tpr: number; tnr: number; kappa: number } }) {
  const trusted = g.enough_labels && g.meets_targets;
  const needed = Math.max(0, g.min_labels - g.n_labels);
  const metric = (name: string, value: string, target: string) => (
    <div>
      <div className="text-xs text-muted">{name}</div>
      <div className="font-display text-xl font-normal tabular-nums tracking-[-0.01em]">{value}</div>
      <div className="text-xs text-faint">target {target}</div>
    </div>
  );
  return (
    <Card className="p-5" aria-label={`${g.grader} calibration`}>
      <CardTitle right={<Badge tone={trusted ? "pass" : "warn"}>{trusted ? "Trusted" : needed ? `Needs ${needed} more labels` : "Below target"}</Badge>}>
        {label(GRADER_LABELS, g.grader)}
      </CardTitle>
      <div className="font-mono text-xs text-muted">{g.grader}</div>
      <div className="mt-4 grid grid-cols-4 gap-3">
        {metric("TPR", pct(g.tpr), `≥ ${pct(targets.tpr)}`)}
        {metric("TNR", pct(g.tnr), `≥ ${pct(targets.tnr)}`)}
        {metric("Accuracy", pct(g.accuracy), "—")}
        {metric("κ", kappa(g.kappa), `≥ ${targets.kappa.toFixed(2)}`)}
      </div>
      <p className="mt-3 text-xs text-muted">
        {g.n_labels} of {g.min_labels} labels · {g.disagreements.length} disagreements
      </p>
    </Card>
  );
}
