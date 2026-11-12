import { getAdminToken } from "./admin";
import type { Snapshot } from "./types";

// Public, compiled into the bundle: the Render API in production, `evalpilot serve` locally.
export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
export const REPORT_URL = process.env.NEXT_PUBLIC_REPORT_URL || "https://tejas2904-rm.github.io/evals-project/report.html";
export const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL || "https://github.com/tejas2904-RM/evals-project";
export const TIMEOUT_MS = 10_000;
const WAKE_DELAYS_MS = [0, 4_000, 8_000, 16_000];

export type Source = "api" | "snapshot";

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
  // 0 = network error or timeout; 502-504 = Render waking up or restarting.
  get unavailable(): boolean {
    return this.status === 0 || this.status === 502 || this.status === 503 || this.status === 504;
  }
}

let snapshot: Promise<Snapshot | null> | null = null;

export function loadSnapshot(): Promise<Snapshot | null> {
  snapshot ??= fetch("/snapshot.json")
    .then((r) => (r.ok ? (r.json() as Promise<Snapshot>) : null))
    .catch(() => null);
  return snapshot;
}

export function resetSnapshotCache(): void {
  snapshot = null;
}

function headers(extra?: HeadersInit): Headers {
  const h = new Headers(extra);
  const token = getAdminToken();
  if (token) h.set("Authorization", `Bearer ${token}`);
  return h;
}

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers: headers(init.headers), signal: controller.signal });
  } catch (err) {
    const timedOut = err instanceof DOMException && err.name === "AbortError";
    throw new ApiError(0, timedOut ? "the API did not answer in time" : "the API is unreachable");
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // not JSON
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export function apiGet<T>(path: string, timeoutMs?: number): Promise<T> {
  return request<T>(path, { method: "GET" }, timeoutMs);
}

/** Retry when Render is asleep or the free instance is too busy to answer. */
export async function withWakeRetry<T>(fn: () => Promise<T>): Promise<T> {
  let last: unknown;
  for (let i = 0; i < WAKE_DELAYS_MS.length; i++) {
    const delay = WAKE_DELAYS_MS[i] ?? 0;
    if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
    try {
      return await fn();
    } catch (err) {
      last = err;
      if (!(err instanceof ApiError) || !err.unavailable || i === WAKE_DELAYS_MS.length - 1) throw err;
    }
  }
  throw last;
}

export function apiPost<T>(path: string, body: unknown, timeoutMs = 90_000): Promise<T> {
  return withWakeRetry(() =>
    request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }, timeoutMs),
  );
}

export function apiPostForm<T>(path: string, form: FormData, timeoutMs = 90_000): Promise<T> {
  return withWakeRetry(() => request<T>(path, { method: "POST", body: form }, timeoutMs));
}

const CACHE_MS = 30_000;
const cache = new Map<string, { at: number; value: Promise<{ data: unknown; source: Source }> }>();

export function clearApiCache(): void {
  cache.clear();
}

/** GET from the API; when it is asleep or down, the same path from the build-time snapshot. Cached for 30 s. */
export function getWithFallback<T>(path: string): Promise<{ data: T; source: Source }> {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < CACHE_MS) return hit.value as Promise<{ data: T; source: Source }>;
  const value = fetchWithFallback<T>(path);
  cache.set(path, { at: Date.now(), value });
  value.then((r) => r.source === "snapshot" && cache.delete(path), () => cache.delete(path));
  return value;
}

async function fetchWithFallback<T>(path: string): Promise<{ data: T; source: Source }> {
  try {
    return { data: await apiGet<T>(path), source: "api" };
  } catch (err) {
    if (!(err instanceof ApiError) || !err.unavailable) throw err;
    const snap = await loadSnapshot();
    const data = snap?.responses[path];
    if (data === undefined) throw err;
    return { data: data as T, source: "snapshot" };
  }
}

export function exportUrl(auditId: string, format: "md" | "pdf"): string {
  return `${API_BASE}/api/audits/${encodeURIComponent(auditId)}/export.${format}`;
}
