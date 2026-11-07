"use client";

import Link from "next/link";
import { Badge, Card, LoadState, PageHeader, SourceBadge } from "@/components/ui";
import { blockingRisks, shortDate } from "@/lib/format";
import { useAudits } from "@/lib/hooks";
import { ROLE_LABELS, SOURCE_LABELS, decisionLabel, label } from "@/lib/labels";

export default function AuditsPage() {
  const { data, loading, error, reload, source } = useAudits();
  return (
    <div className="flex flex-col gap-5">
      <PageHeader eyebrow={<span className="flex items-center gap-2">Full AI system audits <SourceBadge source={source} /></span>} title="Audits" />
      <LoadState loading={loading} error={error} onRetry={reload}>
        <Card className="overflow-x-auto p-5">
          <table className="w-full text-left text-sm">
            <thead className="text-muted">
              <tr className="border-b border-line">
                {["Target", "What", "Verdict", "Risks", "Date", "Source"].map((h) => (
                  <th key={h} scope="col" className="py-2 pr-4 font-normal">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(data ?? []).map((a) => (
                <tr key={a.audit_id} className="border-b border-line last:border-0">
                  <td className="py-3 pr-4">
                    <Link href={`/audits/view/?id=${a.audit_id}`} className="font-medium text-brand underline">
                      {a.target}
                    </Link>
                  </td>
                  <td className="py-3 pr-4 text-muted">{label(ROLE_LABELS, a.role)}</td>
                  <td className="py-3 pr-4">
                    <Badge tone={a.decision === "SHIP" ? "pass" : "fail"}>{decisionLabel(a.decision)}</Badge>
                  </td>
                  <td className="py-3 pr-4 text-muted">
                    {a.n_risks} total · {blockingRisks(a.counts)}
                  </td>
                  <td className="py-3 pr-4 text-muted">{shortDate(a.finished, true)}</td>
                  <td className="py-3 pr-4 text-muted">{label(SOURCE_LABELS, a.source)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {data?.length === 0 && <p className="py-4 text-sm text-muted">No audits yet.</p>}
        </Card>
      </LoadState>
    </div>
  );
}
