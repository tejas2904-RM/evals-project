"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Card, Chip, FilterChip, LoadState, PageHeader, SourceBadge } from "@/components/ui";
import { useMeta, useRun } from "@/lib/hooks";
import { GRADER_LABELS, graderOrder, label } from "@/lib/labels";

export default function ComparePage() {
  return (
    <Suspense fallback={<LoadState loading error={null}>{null}</LoadState>}>
      <Compare />
    </Suspense>
  );
}

function Compare() {
  const router = useRouter();
  const params = useSearchParams();
  const meta = useMeta();
  const run = useRun(meta.data);
  const compares = run.data?.compares ?? [];
  const pair = params.get("pair");
  const current = compares.find((c) => `${c.baseline}-${c.candidate}` === pair) ?? compares[compares.length - 1];

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow={<span className="flex items-center gap-2">Per-check differences between two versions on the same 41 questions <SourceBadge source={run.source} /></span>}
        title="Compare versions"
      />
      <LoadState loading={meta.loading || run.loading} error={meta.error ?? run.error} onRetry={run.reload}>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Version pair">
          {compares.map((c) => {
            const id = `${c.baseline}-${c.candidate}`;
            return (
              <FilterChip key={id} active={current === c} onClick={() => router.replace(`/compare/?pair=${id}`, { scroll: false })}>
                {c.baseline} → {c.candidate}
              </FilterChip>
            );
          })}
        </div>
        {current && (
          <Card className="overflow-x-auto p-5">
            <table className="w-full text-left text-sm">
              <thead className="text-muted">
                <tr className="border-b border-line">
                  {["Check", "Fixed", "Regressed", "Still failing", "Unchanged pass", "n/a"].map((h) => (
                    <th key={h} scope="col" className="py-2 pr-4 font-normal">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {graderOrder(Object.keys(current.graders)).map((g) => {
                  const d = current.graders[g];
                  if (!d) return null;
                  const ids = (list: string[], tone: "pass" | "fail" | "neutral", v: string) =>
                    list.length === 0 ? (
                      <span className="text-faint">—</span>
                    ) : (
                      <div className="flex flex-wrap gap-1">
                        {list.map((id) => (
                          <Link key={id} href={`/cases/?version=${v}&case=${id}`}>
                            <Chip mono tone={tone}>
                              {id}
                            </Chip>
                          </Link>
                        ))}
                      </div>
                    );
                  return (
                    <tr key={g} className="border-b border-line align-top last:border-0">
                      <td className="py-3 pr-4">
                        <div>{label(GRADER_LABELS, g)}</div>
                        <div className="font-mono text-xs text-muted">{g}</div>
                      </td>
                      <td className="py-3 pr-4">{ids(d.fixed, "pass", current.candidate)}</td>
                      <td className="py-3 pr-4">{ids(d.regressed, "fail", current.candidate)}</td>
                      <td className="py-3 pr-4">{ids(d.still_fail, "neutral", current.candidate)}</td>
                      <td className="py-3 pr-4 tabular-nums">{d.still_pass.length}</td>
                      <td className="py-3 pr-4 tabular-nums text-muted">{d.not_comparable.length}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            <p className="mt-3 text-xs text-muted">
              Any regression blocks the release gate (max_regressions_per_grader = 0). n/a: the check doesn&apos;t apply to that question in one of
              the versions.
            </p>
          </Card>
        )}
      </LoadState>
    </div>
  );
}
