"use client";

import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { ApiError, apiGet, getWithFallback, type Source } from "./api";

export type ApiStatus = "ok" | "waking" | "snapshot";

// One status for the whole page, shown by <ApiStatusBar />.
let status: ApiStatus = "ok";
const listeners = new Set<() => void>();

function setStatus(next: ApiStatus): void {
  if (next === status) return;
  status = next;
  listeners.forEach((l) => l());
}

export function useApiStatus(): ApiStatus {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => status,
    () => "ok" as ApiStatus,
  );
}

// Render's free tier sleeps; retry in the background (about a minute in total) while the snapshot is on screen.
export const RETRY_DELAYS_MS = [3_000, 6_000, 12_000, 20_000, 20_000];

export interface ApiState<T> {
  data: T | null;
  source: Source | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
}

export function useApi<T>(path: string | null): ApiState<T> {
  const [state, setState] = useState<{ data: T | null; source: Source | null; error: string | null; loading: boolean }>(
    { data: null, source: null, error: null, loading: path !== null },
  );
  const [nonce, setNonce] = useState(0);
  const reload = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (path === null) {
      setState({ data: null, source: null, error: null, loading: false });
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    setState((s) => ({ ...s, loading: true, error: null }));

    const retry = (attempt: number) => {
      const delay = RETRY_DELAYS_MS[attempt];
      if (delay === undefined) {
        setStatus("snapshot");
        return;
      }
      setStatus("waking");
      timer = setTimeout(async () => {
        try {
          const data = await apiGet<T>(path);
          if (cancelled) return;
          setState({ data, source: "api", error: null, loading: false });
          setStatus("ok");
        } catch (err) {
          if (cancelled) return;
          if (err instanceof ApiError && err.unavailable) retry(attempt + 1);
          else setStatus("snapshot");
        }
      }, delay);
    };

    getWithFallback<T>(path)
      .then(({ data, source }) => {
        if (cancelled) return;
        setState({ data, source, error: null, loading: false });
        if (source === "snapshot") retry(0);
        else setStatus("ok");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : String(err);
        setState({ data: null, source: null, error: message, loading: false });
        if (err instanceof ApiError && err.unavailable) setStatus("snapshot");
      });

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [path, nonce]);

  return { ...state, reload };
}
