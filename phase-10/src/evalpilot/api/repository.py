"""Read access to runs/reference/ (and uploaded audits) for the API, with the same builders as the CLI and report."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from evalpilot.api import views
from evalpilot.config import Settings
from evalpilot.report.build import Sources, audit_dirs, audit_role, audit_summary, build_context, select_audits

RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[A-Za-z0-9-]+$")
AUDIT_ID = re.compile(r"^audit-[A-Za-z0-9-]+$")
UPLOADS = "uploads"
STATUSES = ("passed", "failed", "critical")


class NotFound(LookupError):
    pass


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Repository:
    def __init__(self, settings: Settings, *, local_audits: bool = False) -> None:
        self.settings = settings
        self.reference = settings.runs_dir / "reference"
        self.uploads = settings.runs_dir / UPLOADS
        # Admin mode also lists the owner's own audits under runs/ (never on a hosted service).
        self.local = settings.runs_dir if local_audits else None
        self.critical = views.critical_graders(settings)
        self._contexts: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = threading.Lock()

    # Runs (reference only: the hosted disk is ephemeral, so committed runs are the only durable ones).

    def run_ids(self) -> list[str]:
        if not self.reference.is_dir():
            return []
        return sorted((p.name for p in self.reference.iterdir()
                       if RUN_ID.match(p.name) and (p / "grades.jsonl").is_file()), reverse=True)

    def run_path(self, run_id: str) -> Path:
        if not RUN_ID.match(run_id) or run_id not in self.run_ids():
            raise NotFound(f"run '{run_id}' not found")
        return self.reference / run_id

    def clear_cache(self) -> None:
        with self._lock:
            self._contexts.clear()

    def context(self, run_id: str, version: str) -> dict[str, Any]:
        run = self.run_path(run_id)
        key = (run_id, version)
        with self._lock:
            if key not in self._contexts:
                audits = select_audits(audit_dirs(self.reference / "audits"), run, version)
                src = Sources(run, audits, self.reference / "spend.jsonl", self.settings.labels_path, version)
                self._contexts[key] = build_context(self.settings, src)
            return self._contexts[key]

    def run_summary(self, run_id: str, version: str) -> dict[str, Any]:
        ctx = self.context(run_id, version)
        out = {k: v for k, v in ctx.items() if k not in ("cases", "audits")}
        out["audits"] = [self._brief(a, "reference") for a in ctx["audits"]]
        costs = views.bot_costs(self.run_path(run_id))
        out["version_summaries"] = {v: {**s, "bot_cost_usd": costs.get(v, 0.0)}
                                    for v, s in views.version_summaries(ctx, self.critical).items()}
        out["critical_graders"] = self.critical
        out["judges_trusted"] = views.judges_trusted(ctx["calibration"], ctx["judges"])
        out["documents"] = self.documents()
        return out

    def documents(self) -> dict[str, dict[str, str]]:
        from evalpilot.data import load_corpus

        return {d.doc_id: {"title": d.title, "source": d.source} for d in load_corpus(self.settings.corpus_dir)}

    def run_list(self) -> list[dict[str, Any]]:
        out = []
        for run_id in self.run_ids():
            meta_path = self.reference / run_id / "meta.json"
            meta = _json(meta_path) if meta_path.is_file() else {}
            out.append({"run_id": run_id, "provider": meta.get("provider"), "bot_model": meta.get("bot_model"),
                        "versions": meta.get("versions", []), "finished": meta.get("finished"),
                        "n_traces": meta.get("n_traces")})
        return out

    def cases(self, run_id: str, version: str, *, category: str | None, case_version: str | None,
              failing: str | None, q: str | None, offset: int, limit: int, status: str | None = None) -> dict[str, Any]:
        """`status` and the returned `counts` refer to `case_version` (or `version` when it isn't given)."""
        status_version = case_version or version
        items = []
        counts = {"all": 0, "passed": 0, "failed": 0, "critical": 0}
        needle = (q or "").lower()
        for case in self.context(run_id, version)["cases"]:
            if category and case["category"] != category:
                continue
            versions = {
                v: {**t, "status": views.case_status(t, self.critical)} for v, t in case["versions"].items()
                if (not case_version or v == case_version)
                and (not failing or (failing in t["grades"] and not t["grades"][failing]["passed"]))
            }
            if not versions:
                continue
            if needle and needle not in json.dumps({**case, "versions": versions}, ensure_ascii=False).lower():
                continue
            st = versions.get(status_version, {}).get("status")
            if st:
                counts["all"] += 1
                counts["passed" if st["passed"] else "failed"] += 1
                counts["critical"] += st["critical"]
            if status and not (st and (st["critical"] if status == "critical" else st["passed"] == (status == "passed"))):
                continue
            items.append({**case, "versions": versions})
        return {"total": len(items), "offset": offset, "limit": limit, "status_version": status_version,
                "counts": counts, "items": items[offset:offset + limit]}

    def reference_answers(self, run_id: str, case_id: str, versions: list[str]) -> dict[str, Any]:
        meta = next((r for r in self.run_list() if r["run_id"] == run_id), None)
        if meta is None:
            raise NotFound(f"run '{run_id}' not found")
        ctx = self.context(run_id, (meta["versions"] or ["v3"])[-1])
        case = next((c for c in ctx["cases"] if c["id"] == case_id), None)
        if case is None:
            raise NotFound(f"case '{case_id}' not found in run '{run_id}'")
        answers = {}
        for v in versions:
            t = case["versions"].get(v)
            if t is None:
                raise NotFound(f"case '{case_id}' has no {v} answer in run '{run_id}'")
            answers[v] = {**t, "status": views.case_status(t, self.critical)}
        return {"source": "reference", "run_id": run_id, "case_id": case_id, "query": case["query"],
                "category": case["category"], "answers": answers, "cost_usd": 0.0}

    # Audits: committed reference audits, temporary uploads and (admin only) the owner's local audits.

    def _audit_paths(self) -> list[tuple[Path, str]]:
        found = [(p, "reference") for p in audit_dirs(self.reference / "audits")]
        found += [(p, "upload") for p in audit_dirs(self.uploads)]
        if self.local is not None:
            found += [(p, "local") for p in audit_dirs(self.local)]
        return found

    def audit_path(self, audit_id: str) -> tuple[Path, str]:
        if AUDIT_ID.match(audit_id):
            for path, source in self._audit_paths():
                if path.name == audit_id:
                    return path, source
        raise NotFound(f"audit '{audit_id}' not found")

    @staticmethod
    def _role(intake: dict[str, Any], source: str) -> str:
        role = audit_role(intake)
        if role == "other" and source == "reference" and (intake.get("inputs") or {}).get("trace_version"):
            return "bot"
        return role

    @staticmethod
    def _brief(summary: dict[str, Any], source: str) -> dict[str, Any]:
        v = summary["verdict"]
        return {"audit_id": summary["audit_id"], "role": summary["role"], "source": source, "target": summary["target"],
                "finished": summary["finished"], "provider": summary["provider"], "decision": v["decision"],
                "counts": v["counts"], "n_risks": len(summary["risks"]), "exports": summary["exports"]}

    def audit(self, audit_id: str) -> dict[str, Any]:
        path, source = self.audit_path(audit_id)
        intake = _json(path / "intake.json")
        summary = audit_summary(path, self._role(intake, source))
        risks = sorted(summary["risks"], key=lambda r: -r["severity"])
        return {**summary, "source": source, "risks": views.found_by(path, risks),
                "headline": views.headline(summary["verdict"]), "stats": views.audit_stats(path, intake),
                "guardrails": views.guardrails(summary["coverage"]), "input_kinds": views.input_kinds(intake),
                "rerunnable": source == "local"}

    def audit_list(self) -> list[dict[str, Any]]:
        out = []
        for path, source in self._audit_paths():
            summary = audit_summary(path, self._role(_json(path / "intake.json"), source))
            out.append(self._brief(summary, source))
        return sorted(out, key=lambda a: a["audit_id"], reverse=True)
