"""Planted-flaw answer key (examples/vulnerable_bot/PLANTED_FLAWS.json): found? closed?"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from evalpilot.audit.models import Finding

PLANTED_FILE = "PLANTED_FLAWS.json"
FIXES_FILE = "FIXES.json"


class PlantedFlaw(BaseModel):
    id: str
    title: str
    owasp: str
    where: str = ""
    # Every group must have at least one firing check (prefix match) for the flaw to count as found.
    required: list[list[str]] = Field(min_length=1)
    # Extra detections that may also fire; any of required/also firing means the flaw is still present.
    also: list[str] = Field(default_factory=list)
    fix: str = ""

    @property
    def all_prefixes(self) -> list[str]:
        return [p for group in self.required for p in group] + self.also


class FlawResult(BaseModel):
    id: str
    title: str
    owasp: str
    found: bool
    present: bool
    matched_checks: list[str]


def load_planted(path: Path) -> list[PlantedFlaw]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [PlantedFlaw.model_validate(f) for f in data["flaws"]]


def planted_file_for(code_root: Path | None) -> Path | None:
    """PLANTED_FLAWS.json in the target, or the file FIXES.json points to (for the fixed variant)."""
    if code_root is None:
        return None
    if (code_root / PLANTED_FILE).is_file():
        return code_root / PLANTED_FILE
    fixes = code_root / FIXES_FILE
    if fixes.is_file():
        ref = json.loads(fixes.read_text(encoding="utf-8")).get("planted_flaws")
        if ref and (code_root / ref).resolve().is_file():
            return (code_root / ref).resolve()
    return None


def evaluate(flaws: list[PlantedFlaw], findings: list[Finding]) -> list[FlawResult]:
    fired = sorted({f.check_id for f in findings})
    results = []
    for flaw in flaws:
        matched = sorted({c for c in fired if any(c.startswith(p) for p in flaw.all_prefixes)})
        found = all(any(c.startswith(p) for c in fired for p in group) for group in flaw.required)
        results.append(FlawResult(id=flaw.id, title=flaw.title, owasp=flaw.owasp, found=found, present=bool(matched), matched_checks=matched))
    return results
