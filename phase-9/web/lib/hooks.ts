"use client";

import { useAdminToken } from "./admin";
import type { AuditBrief, Meta, RunSummary } from "./types";
import { useApi } from "./useApi";

export function useMeta() {
  return useApi<Meta>("/api/meta");
}

export function useRun(meta: Meta | null, version = "v3") {
  const runId = meta?.runs[0] ?? null;
  return useApi<RunSummary>(runId ? `/api/runs/${runId}?version=${version}` : null);
}

export function useAudits() {
  return useApi<AuditBrief[]>("/api/audits");
}

/** Admin features need both: a server in admin mode and this tab signed in with its token. */
export function useAdmin(meta: Meta | null): { signedIn: boolean; serverAdmin: boolean } {
  const token = useAdminToken();
  const serverAdmin = Boolean(meta?.admin);
  return { signedIn: serverAdmin && Boolean(token), serverAdmin };
}
