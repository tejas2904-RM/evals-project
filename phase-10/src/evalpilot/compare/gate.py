"""Release gate from evals.toml [gate]: min pass rates, max regressions, required improvements."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from evalpilot.compare.diff import diff_grades, for_version
from evalpilot.config import ConfigError, GateConfig
from evalpilot.graders.base import is_na
from evalpilot.graders.registry import GRADER_NAMES
from evalpilot.models import VERSIONS, GradeRecord


@dataclass(frozen=True)
class Violation:
    grader: str
    rule: str
    threshold: str
    observed: str
    case_ids: list[str]

    def line(self) -> str:
        return f"{self.grader} | {self.rule} | {self.threshold} | {self.observed} | {', '.join(self.case_ids) or '-'}"


@dataclass
class GateResult:
    version: str
    baseline: str | None
    passed: bool
    violations: list[Violation]
    pass_rates: dict[str, dict[str, Any]]
    warnings: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "BLOCKED"

    def to_dict(self) -> dict[str, Any]:
        return {"version": self.version, "baseline": self.baseline, "verdict": self.verdict,
                "violations": [asdict(v) for v in self.violations],
                "pass_rates": self.pass_rates, "warnings": self.warnings}


def default_baseline(version: str) -> str | None:
    """The previous bot version (v3 -> v2); v1 has none."""
    i = VERSIONS.index(version) if version in VERSIONS else -1
    return VERSIONS[i - 1] if i > 0 else None


def validate(cfg: GateConfig) -> None:
    named = set(cfg.min_pass_rate) | {g for gs in cfg.required_improvements.values() for g in gs}
    if unknown := sorted(named - set(GRADER_NAMES)):
        raise ConfigError(f"evals.toml: [gate] names unknown grader(s) {unknown}")


def _rate(records: list[GradeRecord]) -> dict[str, Any]:
    applicable = [r for r in records if not is_na(r)]
    passed = sum(r.passed for r in applicable)
    return {
        "passed": passed,
        "applicable": len(applicable),
        "na": len(records) - len(applicable),
        "rate": passed / len(applicable) if applicable else None,
        "failing": sorted(r.case_id for r in applicable if not r.passed),
    }


def _fmt(stats: dict[str, Any]) -> str:
    return f"{stats['passed']}/{stats['applicable']} ({stats['rate']:.0%})" if stats["rate"] is not None else "no applicable cases"


def evaluate_gate(
    records: Iterable[GradeRecord], version: str, cfg: GateConfig, *, baseline: str | None = None
) -> GateResult:
    validate(cfg)
    records = list(records)
    cand = for_version(records, version)
    if not cand:
        raise ValueError(f"no grades for version {version}")
    by_grader: dict[str, list[GradeRecord]] = {}
    for r in cand:
        by_grader.setdefault(r.grader, []).append(r)
    rates = {g: _rate(rs) for g, rs in sorted(by_grader.items())}
    violations: list[Violation] = []
    warnings: list[str] = []

    for grader, threshold in cfg.min_pass_rate.items():
        stats = rates.get(grader)
        if stats is None:
            violations.append(Violation(grader, "missing_grades", f">= {threshold:.0%}", "not graded", []))
        elif stats["rate"] is None:
            warnings.append(f"{grader}: no applicable cases for {version}; min_pass_rate not checked")
        elif stats["rate"] < threshold:
            violations.append(Violation(grader, "min_pass_rate", f">= {threshold:.0%}", _fmt(stats), stats["failing"]))
    for grader in sorted(set(rates) - set(cfg.min_pass_rate)):
        warnings.append(f"{grader}: no min_pass_rate in evals.toml")

    if baseline is not None:
        base = for_version(records, baseline)
        if not base:
            raise ValueError(f"no grades for baseline version {baseline}")
        comparison = diff_grades(base, cand, baseline_label=baseline, candidate_label=version)
        for grader, d in comparison.graders.items():
            if len(d.regressed) > cfg.max_regressions_per_grader:
                violations.append(Violation(
                    grader, f"regressions_vs_{baseline}", f"<= {cfg.max_regressions_per_grader}",
                    str(len(d.regressed)), d.regressed,
                ))
        base_rates = {g: _rate([r for r in base if r.grader == g]) for g in rates}
        for grader in cfg.required_improvements.get(f"{version}_over_{baseline}", []):
            b, c = base_rates.get(grader), rates.get(grader)
            if b is None or c is None:
                violations.append(Violation(grader, f"improvement_over_{baseline}", "graded on both", "not graded", []))
            elif b["applicable"] and b["passed"] == b["applicable"]:
                # Ceiling: a perfect baseline can't be beaten, so the requirement becomes "no regression",
                # which the regression rule above already enforces.
                warnings.append(
                    f"{grader}: {baseline} already passes {_fmt(b)}; improvement over {baseline} "
                    f"checked as no regression"
                )
            elif c["passed"] <= b["passed"]:
                violations.append(Violation(
                    grader, f"improvement_over_{baseline}", f"> {b['passed']} passes ({baseline}: {_fmt(b)})",
                    f"{c['passed']} passes ({_fmt(c)})", c["failing"],
                ))
    elif any(k.startswith(f"{version}_over_") for k in cfg.required_improvements):
        warnings.append(f"no baseline given; required improvements for {version} not checked")

    return GateResult(version, baseline, not violations, violations, rates, warnings)
