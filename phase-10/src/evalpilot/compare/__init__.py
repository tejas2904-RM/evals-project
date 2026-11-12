"""Phase 6: run comparison and the release gate."""

from evalpilot.compare.diff import OUTCOMES, Comparison, GraderDiff, diff_grades, for_version
from evalpilot.compare.gate import GateResult, Violation, default_baseline, evaluate_gate

__all__ = [
    "OUTCOMES",
    "Comparison",
    "GateResult",
    "GraderDiff",
    "Violation",
    "default_baseline",
    "diff_grades",
    "evaluate_gate",
    "for_version",
]
