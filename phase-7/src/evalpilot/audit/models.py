"""Audit data model: engines emit Findings and CheckOutcomes; the risk engine merges findings into Risks."""

from __future__ import annotations

import hashlib
from typing import Any, Literal

from pydantic import BaseModel, Field

Engine = Literal["behaviour", "security", "code", "config"]
ENGINES: tuple[Engine, ...] = ("behaviour", "security", "code", "config")
Level = Literal["critical", "high", "medium", "low"]
LEVELS: tuple[Level, ...] = ("critical", "high", "medium", "low")
Status = Literal["open", "closed", "accepted"]
CellStatus = Literal["declared", "verified", "failed", "missing", "n/a"]
# Where a finding came from; an AI-review finding corroborated by any other source gains +1 likelihood.
Source = Literal["rule", "tool", "probe", "grader", "card", "ai"]


class Evidence(BaseModel):
    kind: Literal["file_line", "probe_transcript", "trace", "config_key"]
    location: str
    excerpt: str = ""


class Finding(BaseModel):
    engine: Engine
    check_id: str
    owasp: str | None = None
    title: str
    evidence: list[Evidence] = Field(min_length=1)
    likelihood: int = Field(ge=1, le=5)
    impact: int = Field(ge=1, le=5)
    fix: str
    merge_key: str
    source: Source = "rule"
    finding_id: str = ""


class CheckOutcome(BaseModel):
    """One check that ran, pass or fail. Passing checks are what make a coverage cell `verified`."""

    engine: Engine
    check_id: str
    passed: bool
    owasp: str | None = None


class Risk(BaseModel):
    risk_id: str
    owasp: str | None
    title: str
    findings: list[str]
    check_ids: list[str]
    evidence: list[Evidence]
    likelihood: int
    impact: int
    severity: int
    level: Level
    fix: str
    status: Status = "open"
    acceptance: dict[str, str] | None = None
    # Set when every finding is uncorroborated AI review and the level was capped (see [audit.verdict]).
    capped_from: Level | None = None


class Verdict(BaseModel):
    decision: Literal["SHIP", "BLOCK"]
    deciding_risks: list[str]
    reasons: list[str]
    conditions: list[str]
    counts: dict[str, int]


class CoverageCell(BaseModel):
    layer: str
    threats: list[str]
    declared: bool
    status: CellStatus
    passed_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)


class EngineResult(BaseModel):
    engine: Engine
    findings: list[Finding] = Field(default_factory=list)
    checks: list[CheckOutcome] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    transcripts: list[dict[str, Any]] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)


def risk_id_for(merge_key: str) -> str:
    """Stable across audits, so `audit-diff` can match the same root cause in two runs."""
    return "R-" + hashlib.sha1(merge_key.encode("utf-8")).hexdigest()[:8]
