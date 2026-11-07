// Contract between the Python API and lib/types.ts. `evalpilot snapshot` writes public/snapshot.json from the real
// app; the type assertions below fail `npm run typecheck` when a field is renamed, dropped or changes type, and the
// runtime checks fail `npm test` when a path the pages request is missing from the snapshot.
import snap from "@/public/snapshot.json";
import type { AuditBrief, AuditDetail, CasePage, Estimate, FinalVerdict, Meta, RunListItem, RunSummary } from "@/lib/types";
import { snapshot } from "./fixtures";

type R = (typeof snap)["responses"];
type At<P extends string> = R[Extract<keyof R, P>];
type Exists<T> = [T] extends [never] ? false : true;
type Assert<T extends U, U> = T;

export type Contract = [
  Assert<Exists<At<"/api/meta">>, true>,
  Assert<At<"/api/meta">, Meta>,
  Assert<At<"/api/runs">, RunListItem[]>,
  Assert<At<"/api/audits">, AuditBrief[]>,
  Assert<At<"/api/estimate">, Estimate>,
  Assert<Exists<At<`/api/runs/${string}?version=v3`>>, true>,
  Assert<At<`/api/runs/${string}?version=v3`>, RunSummary>,
  Assert<Exists<At<`/api/runs/${string}/cases?${string}`>>, true>,
  Assert<At<`/api/runs/${string}/cases?${string}`>, CasePage>,
  Assert<Exists<At<`/api/verdict?${string}`>>, true>,
  Assert<At<`/api/verdict?${string}`>, FinalVerdict>,
  Assert<Exists<At<`/api/audits/${string}`>>, true>,
  Assert<At<`/api/audits/${string}`>, AuditDetail>,
];

const responses = snapshot.responses as Record<string, Record<string, unknown>>;
const meta = responses["/api/meta"] as unknown as Meta;

describe("snapshot contract", () => {
  it("is the current format", () => {
    expect(snapshot.format).toBe(1);
    expect(snapshot.as_of).toMatch(/^\d{4}-\d\d-\d\dT/);
  });

  it("has every path the pages request", () => {
    const runId = meta.runs[0];
    const expected = [
      "/api/meta",
      "/api/runs",
      "/api/audits",
      "/api/estimate",
      `/api/runs/${runId}?version=v3`,
      ...meta.versions.map((v) => `/api/runs/${runId}/cases?case_version=${v}&limit=100`),
      ...meta.versions.map((v) => `/api/verdict?version=${v}`),
    ];
    for (const path of expected) expect(responses, path).toHaveProperty([path]);
  });

  it("has every reference audit", () => {
    const briefs = responses["/api/audits"] as unknown as AuditBrief[];
    const reference = briefs.filter((a) => a.source === "reference");
    expect(reference.length).toBeGreaterThanOrEqual(3);
    for (const a of reference) expect(responses).toHaveProperty([`/api/audits/${a.audit_id}`]);
  });

  it("is keyless: the public snapshot is the read-only, offline app", () => {
    expect(meta.mode).toBe("readonly");
    expect(meta.admin).toBe(false);
    expect(meta.provider).toBe("offline");
    expect(JSON.stringify(snapshot)).not.toMatch(/sk-[A-Za-z0-9_-]{20,}/);
  });

  it("gives every case a status for every version", () => {
    for (const v of meta.versions) {
      const page = responses[`/api/runs/${meta.runs[0]}/cases?case_version=${v}&limit=100`] as unknown as CasePage;
      expect(page.items.length).toBe(page.total);
      for (const item of page.items) expect(item.versions[v]?.status, `${item.id} ${v}`).toBeDefined();
    }
  });
});
