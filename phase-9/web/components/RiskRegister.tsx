"use client";

import { useMemo, useState } from "react";
import { Badge, Card, CardTitle, cx, levelTone } from "@/components/ui";
import { OWASP_NAMES, label } from "@/lib/labels";
import type { Risk } from "@/lib/types";

const LEVELS = ["critical", "high", "medium", "low"];
const SELECT = "rounded-lg border border-line bg-white px-2 py-1.5 text-sm";

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function RiskRegister({ risks, title = "Risk register", empty = "No risks found." }: { risks: Risk[]; title?: string; empty?: string }) {
  const [level, setLevel] = useState("all");
  const [owasp, setOwasp] = useState("all");
  const [open, setOpen] = useState<string | null>(() => [...risks].sort((a, b) => b.severity - a.severity)[0]?.risk_id ?? null);
  const categories = useMemo(() => [...new Set(risks.map((r) => r.owasp).filter((o): o is string => Boolean(o)))].sort(), [risks]);
  const shown = risks
    .filter((r) => (level === "all" || r.level === level) && (owasp === "all" || r.owasp === owasp))
    .sort((a, b) => b.severity - a.severity);

  return (
    <Card className="p-5">
      <CardTitle
        right={
          <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
            <label className="flex items-center gap-1.5">
              Severity
              <select className={SELECT} value={level} onChange={(e) => setLevel(e.target.value)}>
                <option value="all">All</option>
                {LEVELS.map((l) => (
                  <option key={l} value={l}>
                    {cap(l)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1.5">
              OWASP
              <select className={SELECT} value={owasp} onChange={(e) => setOwasp(e.target.value)}>
                <option value="all">All categories</option>
                {categories.map((c) => (
                  <option key={c} value={c}>
                    {c} {label(OWASP_NAMES, c)}
                  </option>
                ))}
              </select>
            </label>
          </div>
        }
      >
        {title}
      </CardTitle>
      {shown.length === 0 ? (
        <p className="mt-4 text-sm text-muted">{empty}</p>
      ) : (
        <ul className="mt-3 divide-y divide-line" aria-label="Risks">
          {shown.map((r) => {
            const expanded = open === r.risk_id;
            return (
              <li key={r.risk_id} className="py-1">
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(expanded ? null : r.risk_id)}
                  className="grid w-full grid-cols-[76px_1fr] items-center gap-3 py-2.5 text-left sm:grid-cols-[76px_1fr_auto]"
                >
                  <Badge tone={levelTone(r.level)} className="w-[70px] justify-center">
                    {cap(r.level)}
                  </Badge>
                  <span className="text-sm font-medium">{r.title}</span>
                  <span className="col-start-2 flex gap-4 text-xs text-muted sm:col-start-auto">
                    <span>{r.owasp ? `${r.owasp} ${label(OWASP_NAMES, r.owasp)}` : "—"}</span>
                    <span className={cx(r.status === "accepted" && "text-warn")}>{cap(r.status)}</span>
                  </span>
                </button>
                {expanded && (
                  <dl className="mb-3 grid grid-cols-[90px_1fr] gap-x-4 gap-y-2 rounded-lg bg-neutral-soft/70 p-4 text-sm">
                    <dt className="text-muted">Evidence</dt>
                    <dd className="flex min-w-0 flex-col gap-1.5">
                      {r.evidence.map((e, i) => (
                        <div key={`${e.location}-${i}`} className="min-w-0">
                          <span className="font-mono text-xs">{e.location}</span>
                          {e.excerpt && <pre className="mt-0.5 whitespace-pre-wrap break-words font-mono text-xs text-muted">{e.excerpt}</pre>}
                        </div>
                      ))}
                    </dd>
                    <dt className="text-muted">Found by</dt>
                    <dd>{r.found_by.length ? r.found_by.join(", ") : r.check_ids.join(", ")}</dd>
                    <dt className="text-muted">Score</dt>
                    <dd>
                      Likelihood {r.likelihood} × impact {r.impact} = {r.severity}
                      {r.capped_from && <span className="text-muted"> (AI-only finding, capped from {r.capped_from})</span>}
                    </dd>
                    <dt className="text-muted">Fix</dt>
                    <dd>{r.fix}</dd>
                    {r.acceptance && (
                      <>
                        <dt className="text-muted">Accepted</dt>
                        <dd>
                          {Object.entries(r.acceptance)
                            .map(([k, v]) => `${k}: ${v}`)
                            .join(" · ")}
                        </dd>
                      </>
                    )}
                  </dl>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
