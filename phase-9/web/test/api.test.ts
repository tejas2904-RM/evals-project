import { act, renderHook, waitFor } from "@testing-library/react";
import { API_BASE, ApiError, apiGet, getWithFallback } from "@/lib/api";
import { setAdminToken } from "@/lib/admin";
import { RETRY_DELAYS_MS, useApi, useApiStatus } from "@/lib/useApi";
import { fakeApi, meta } from "./fixtures";

describe("API client", () => {
  it("returns API data when the API answers", async () => {
    fakeApi();
    const r = await getWithFallback<{ mode: string }>("/api/meta");
    expect(r.source).toBe("api");
    expect(r.data.mode).toBe("readonly");
  });

  it("turns a timeout into an 'unavailable' error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init: RequestInit) => new Promise((_, reject) => init.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))))),
    );
    const err = await apiGet("/api/meta", 20).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(0);
    expect((err as ApiError).unavailable).toBe(true);
    expect((err as ApiError).message).toMatch(/in time/);
  });

  it("does not fall back on a 404: a wrong id is an error, not stale data", async () => {
    fakeApi();
    const err = await getWithFallback("/api/audits/nope").catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(404);
    expect((err as ApiError).unavailable).toBe(false);
  });

  it("falls back to the snapshot when the API is down", async () => {
    fakeApi({}, { down: true });
    const r = await getWithFallback<{ runs: string[] }>("/api/meta");
    expect(r.source).toBe("snapshot");
    expect(r.data.runs).toEqual(meta().runs);
  });

  it("falls back on 503 (Render waking up)", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/snapshot.json" ? new Response(JSON.stringify({ format: 1, evalpilot_version: "x", as_of: "", responses: { "/api/runs": [] } })) : new Response("", { status: 503 }),
      ),
    );
    const { clearApiCache, resetSnapshotCache } = await import("@/lib/api");
    clearApiCache();
    resetSnapshotCache();
    expect((await getWithFallback("/api/runs")).source).toBe("snapshot");
  });

  it("sends the admin token only once signed in", async () => {
    const api = fakeApi();
    await apiGet("/api/meta");
    setAdminToken("t0ken");
    await apiGet("/api/meta");
    const [first, second] = api.calls();
    expect(first?.path).toBe(`${API_BASE}/api/meta`);
    expect(new Headers(first?.init?.headers).get("Authorization")).toBeNull();
    expect(new Headers(second?.init?.headers).get("Authorization")).toBe("Bearer t0ken");
  });

  it("shows the snapshot, then retries in the background until the API wakes", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const api = fakeApi({}, { down: true });
    const { result } = renderHook(() => ({ state: useApi<{ mode: string }>("/api/meta"), status: useApiStatus() }));
    await waitFor(() => expect(result.current.state.source).toBe("snapshot"));
    expect(result.current.status).toBe("waking");

    api.fetch.mockImplementation(async () => new Response(JSON.stringify({ ...meta(), mode: "jobs" })));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(RETRY_DELAYS_MS[0] ?? 0);
    });
    await waitFor(() => expect(result.current.state.source).toBe("api"));
    expect(result.current.state.data?.mode).toBe("jobs");
    expect(result.current.status).toBe("ok");
  });
});
