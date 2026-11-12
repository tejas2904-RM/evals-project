import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";
import { API_BASE, clearApiCache, resetSnapshotCache } from "@/lib/api";
import type { AuditBrief, AuditDetail, Meta, Snapshot } from "@/lib/types";

export const snapshot = JSON.parse(
  readFileSync(resolve(process.cwd(), "public/snapshot.json"), "utf8"),
) as Snapshot;

export function response<T>(path: string): T {
  const data = snapshot.responses[path];
  if (data === undefined) throw new Error(`snapshot has no ${path}`);
  return structuredClone(data) as T;
}

export const meta = () => response<Meta>("/api/meta");
export const audits = () => response<AuditBrief[]>("/api/audits");
export const runPath = () => `/api/runs/${meta().runs[0]}?version=v3`;
export const vulnerableAudit = () => {
  const brief = audits().find((a) => a.role === "vulnerable");
  if (!brief) throw new Error("snapshot has no vulnerable audit");
  return response<AuditDetail>(`/api/audits/${brief.audit_id}`);
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export interface FakeApi {
  fetch: ReturnType<typeof vi.fn>;
  calls: () => { path: string; init: RequestInit | undefined }[];
}

/** Serve snapshot responses as if they came from the API; `overrides` replace or add paths. */
export function fakeApi(overrides: Record<string, unknown> = {}, { down = false } = {}): FakeApi {
  clearApiCache();
  resetSnapshotCache();
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === "/snapshot.json") return json(snapshot);
    if (down) throw new TypeError("Failed to fetch");
    const path = url.startsWith(API_BASE) ? url.slice(API_BASE.length) : url;
    if (path in overrides) return json(overrides[path]);
    const data = snapshot.responses[path];
    return data === undefined ? json({ detail: "Not Found" }, 404) : json(data);
  });
  vi.stubGlobal("fetch", fn);
  return {
    fetch: fn,
    calls: () => fn.mock.calls.map(([input, init]) => ({ path: String(input), init: init as RequestInit | undefined })),
  };
}
