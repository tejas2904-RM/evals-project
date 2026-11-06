"""Read access to runs/reference/ (and uploaded audits) for the API, with the same builders as the CLI and report."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

from evalpilot.config import Settings
from evalpilot.report.build import Sources, audit_dirs, audit_role, audit_summary, build_context, select_audits

RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[A-Za-z0-9-]+$")
AUDIT_ID = re.compile(r"^audit-[A-Za-z0-9-]+$")
UPLOADS = "uploads"


class NotFound(LookupError):
    pass


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class Repository:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.reference = settings.runs_dir / "reference"
        self.uploads = settings.runs_dir / UPLOADS
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
        return out

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
              failing: str | None, q: str | None, offset: int, limit: int) -> dict[str, Any]:
        items = []
        needle = (q or "").lower()
        for case in self.context(run_id, version)["cases"]:
            if category and case["category"] != category:
                continue
            versions = {
                v: t for v, t in case["versions"].items()
                if (not case_version or v == case_version)
                and (not failing or (failing in t["grades"] and not t["grades"][failing]["passed"]))
            }
            if not versions:
                continue
            if needle and needle not in json.dumps({**case, "versions": versions}, ensure_ascii=False).lower():
                continue
            items.append({**case, "versions": versions})
        return {"total": len(items), "offset": offset, "limit": limit, "items": items[offset:offset + limit]}

    # Audits: committed reference audits plus temporary uploads.

    def _audit_paths(self) -> list[tuple[Path, str]]:
        found = [(p, "reference") for p in audit_dirs(self.reference / "audits")]
        found += [(p, "upload") for p in audit_dirs(self.uploads)]
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
        summary = audit_summary(path, self._role(_json(path / "intake.json"), source))
        summary["risks"] = sorted(summary["risks"], key=lambda r: -r["severity"])
        return {**summary, "source": source}

    def audit_list(self) -> list[dict[str, Any]]:
        out = []
        for path, source in self._audit_paths():
            summary = audit_summary(path, self._role(_json(path / "intake.json"), source))
            out.append(self._brief(summary, source))
        return sorted(out, key=lambda a: a["audit_id"], reverse=True)
