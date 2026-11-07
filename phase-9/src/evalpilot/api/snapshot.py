"""Read-only API responses for runs/reference/, keyed by request path, for the web app's offline fallback.

The keys are exactly the paths the web client requests, so the fallback shows what the API would have returned.
"""

from __future__ import annotations

from typing import Any

from evalpilot import __version__

SNAPSHOT_FORMAT = 1
CASE_PAGE = 100


def snapshot_paths(meta: dict[str, Any], audits: list[dict[str, Any]]) -> list[str]:
    paths = ["/api/meta", "/api/runs", "/api/audits", "/api/estimate"]
    for run_id in meta["runs"][:1]:
        paths.append(f"/api/runs/{run_id}?version=v3")
        paths += [f"/api/runs/{run_id}/cases?case_version={v}&limit={CASE_PAGE}" for v in meta["versions"]]
    paths += [f"/api/verdict?version={v}" for v in meta["versions"]]
    paths += [f"/api/audits/{a['audit_id']}" for a in audits if a["source"] == "reference"]
    return paths


def build_snapshot(client: Any) -> dict[str, Any]:
    """`client` is a TestClient over the read-only app; every response must be 200."""
    meta = client.get("/api/meta").json()
    audits = client.get("/api/audits").json()
    responses: dict[str, Any] = {}
    for path in snapshot_paths(meta, audits):
        r = client.get(path)
        if r.status_code != 200:
            raise RuntimeError(f"snapshot: GET {path} -> {r.status_code} {r.text[:200]}")
        responses[path] = r.json()
    as_of = max((a["finished"] or "" for a in audits), default="")
    return {"format": SNAPSHOT_FORMAT, "evalpilot_version": __version__, "as_of": as_of, "responses": responses}
