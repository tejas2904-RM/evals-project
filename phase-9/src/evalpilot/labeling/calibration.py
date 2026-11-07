"""Agreement between graders and human labels (positive class = pass), and AI-review precision."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any

from evalpilot.audit.flaws import PlantedFlaw
from evalpilot.audit.models import Finding
from evalpilot.config import CalibrationConfig
from evalpilot.graders.base import is_na
from evalpilot.graders.llm import JUDGE_NAMES
from evalpilot.models import GradeRecord, Label

AI_REVIEW_GRADER = "ai_review"


@dataclass(frozen=True)
class Confusion:
    tp: int = 0  # grader pass, human pass
    fp: int = 0  # grader pass, human fail
    tn: int = 0  # grader fail, human fail
    fn: int = 0  # grader fail, human pass

    @property
    def n(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @classmethod
    def from_pairs(cls, pairs: Iterable[tuple[bool, bool]]) -> Confusion:
        """pairs = (grader_pass, human_pass)."""
        tp = fp = tn = fn = 0
        for grader, human in pairs:
            if grader and human:
                tp += 1
            elif grader:
                fp += 1
            elif human:
                fn += 1
            else:
                tn += 1
        return cls(tp, fp, tn, fn)


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


def tpr(c: Confusion) -> float | None:
    """Of the answers a human passed, how many did the grader pass."""
    return _ratio(c.tp, c.tp + c.fn)


def tnr(c: Confusion) -> float | None:
    """Of the answers a human failed, how many did the grader fail."""
    return _ratio(c.tn, c.tn + c.fp)


def accuracy(c: Confusion) -> float | None:
    return _ratio(c.tp + c.tn, c.n)


def cohen_kappa(c: Confusion) -> float | None:
    """(p_o - p_e) / (1 - p_e); None when both raters used a single class (kappa undefined)."""
    if not c.n:
        return None
    p_o = (c.tp + c.tn) / c.n
    grader_pass, human_pass = (c.tp + c.fp) / c.n, (c.tp + c.fn) / c.n
    p_e = grader_pass * human_pass + (1 - grader_pass) * (1 - human_pass)
    if p_e >= 1.0:
        return None
    return (p_o - p_e) / (1 - p_e)


@dataclass
class GraderCalibration:
    grader: str
    kind: str
    n_labels: int
    min_labels: int
    confusion: dict[str, int]
    tpr: float | None
    tnr: float | None
    accuracy: float | None
    kappa: float | None
    enough_labels: bool
    meets_targets: bool
    disagreements: list[dict[str, Any]] = field(default_factory=list)
    unmatched_labels: int = 0


def calibrate_grader(
    grader: str, labels: Iterable[Label], grades: dict[tuple[str, str, str], GradeRecord], cfg: CalibrationConfig
) -> GraderCalibration:
    """Join labels to grades on (case_id, version, grader); n/a grades and missing grades are not scored."""
    pairs, disagreements, unmatched = [], [], 0
    for label in labels:
        record = grades.get((label.case_id, label.version, grader))
        if record is None or is_na(record):
            unmatched += 1
            continue
        pairs.append((record.passed, label.human_pass))
        if record.passed != label.human_pass:
            disagreements.append({
                "case_id": label.case_id,
                "version": label.version,
                "grader_pass": record.passed,
                "human_pass": label.human_pass,
                "evidence": record.evidence[:300],
            })
    c = Confusion.from_pairs(pairs)
    is_judge = grader in JUDGE_NAMES
    minimum = cfg.min_per_judge if is_judge else cfg.min_per_code_grader
    k, t_pos, t_neg = cohen_kappa(c), tpr(c), tnr(c)
    meets = (
        t_pos is not None and t_pos >= cfg.target_tpr
        and t_neg is not None and t_neg >= cfg.target_tnr
        and k is not None and k >= cfg.target_kappa
    )
    return GraderCalibration(
        grader=grader,
        kind="llm" if is_judge else "code",
        n_labels=c.n,
        min_labels=minimum,
        confusion=asdict(c),
        tpr=t_pos,
        tnr=t_neg,
        accuracy=accuracy(c),
        kappa=k,
        enough_labels=c.n >= minimum,
        meets_targets=meets,
        disagreements=disagreements,
        unmatched_labels=unmatched,
    )


def calibrate(
    labels: Iterable[Label], grades: Iterable[GradeRecord], cfg: CalibrationConfig, *, run_id: str
) -> dict[str, Any]:
    """Per-grader calibration for one run. Labels from other runs judged different answers, so they are ignored."""
    by_key = {(g.case_id, g.version, g.grader): g for g in grades}
    labels = [lb for lb in labels if lb.run_id == run_id and lb.grader != AI_REVIEW_GRADER]
    graders = sorted({lb.grader for lb in labels} | set(JUDGE_NAMES))
    results = {
        name: calibrate_grader(name, [lb for lb in labels if lb.grader == name], by_key, cfg) for name in graders
    }
    judges = [results[n] for n in JUDGE_NAMES]
    judge_total = sum(r.n_labels for r in judges)
    problems = [f"{r.grader}: {r.n_labels} labels < {r.min_labels}" for r in judges if not r.enough_labels]
    if judge_total < cfg.min_labels:
        problems.append(f"judge labels in total: {judge_total} < {cfg.min_labels}")
    return {
        "run_id": run_id,
        "positive_class": "pass",
        "targets": {"tpr": cfg.target_tpr, "tnr": cfg.target_tnr, "kappa": cfg.target_kappa},
        "min_labels": cfg.min_labels,
        "judge_labels": judge_total,
        "enough_labels": not problems,
        "problems": problems,
        "graders": {name: asdict(r) for name, r in results.items()},
    }


# ---- AI code review vs the planted-flaw answer key ----------------------------------------------

_LOC_RE = re.compile(r"^(?P<file>[^:]+):(?P<start>\d+)(?:-(?P<end>\d+))?$")
LINE_SLACK = 2


def _span(location: str) -> tuple[str, int, int] | None:
    m = _LOC_RE.match(location.replace("\\", "/"))
    if not m:
        return None
    start = int(m["start"])
    return m["file"].rsplit("/", 1)[-1], start, int(m["end"] or start)


def _overlaps(a: Finding, b: Finding) -> bool:
    spans_b = [s for e in b.evidence if (s := _span(e.location))]
    for ev in a.evidence:
        sa = _span(ev.location)
        if sa and any(sa[0] == sb[0] and sa[1] <= sb[2] + LINE_SLACK and sb[1] <= sa[2] + LINE_SLACK for sb in spans_b):
            return True
    return False


def ai_item_id(f: Finding) -> str:
    return f"{f.check_id}@{f.evidence[0].location}"


def match_flaw(f: Finding, flaws: list[PlantedFlaw], others: list[Finding]) -> str | None:
    """Planted flaw an AI finding points at: a non-AI check that detects the flaw shares its merge key
    or fires on the same lines. Same file + same OWASP alone is not enough (one file can hold several flaws)."""
    peers = [o.check_id for o in others if o.merge_key == f.merge_key or _overlaps(f, o)]
    for flaw in flaws:
        if any(p.startswith(prefix) for p in peers for prefix in flaw.all_prefixes):
            return flaw.id
    return None


def ai_review_precision(
    audit_id: str,
    variant: str,
    findings: list[Finding],
    flaws: list[PlantedFlaw],
    stats: dict[str, Any],
    labels: Iterable[Label] = (),
) -> dict[str, Any]:
    """variant = "vulnerable" (flaws planted) or "fixed" (every planted flaw should be gone).

    precision_planted counts only answer-key matches, so it is a lower bound: an AI finding can be a real
    issue the key doesn't list. Human labels (grader=ai_review, p = real, f = false positive) settle those.
    """
    ai = [f for f in findings if f.source == "ai"]
    others = [f for f in findings if f.source != "ai"]
    reviewed = {lb.case_id: lb.human_pass for lb in labels if lb.run_id == audit_id and lb.grader == AI_REVIEW_GRADER}
    planted_hits = flaws if variant == "vulnerable" else []
    items, matched_flaws = [], set()
    for f in ai:
        flaw_id = match_flaw(f, planted_hits, others)
        if flaw_id:
            matched_flaws.add(flaw_id)
        item_id = ai_item_id(f)
        items.append({
            "id": item_id,
            "title": f.title,
            "owasp": f.owasp,
            "location": f.evidence[0].location,
            "corroborated": any(o.merge_key == f.merge_key for o in others),
            "planted_flaw": flaw_id,
            "human_real": reviewed.get(item_id),
        })
    kept = len(ai)
    planted = sum(1 for it in items if it["planted_flaw"])
    real = sum(1 for it in items if not it["planted_flaw"] and it["human_real"] is True)
    false = sum(1 for it in items if not it["planted_flaw"] and it["human_real"] is False)
    unreviewed = kept - planted - real - false
    proposed = int(stats.get("findings_proposed", kept))
    rejected = int(stats.get("rejected", 0))
    out: dict[str, Any] = {
        "audit_id": audit_id,
        "variant": variant,
        "files_reviewed": stats.get("files_reviewed"),
        "proposed": proposed,
        "rejected_evidence": rejected,
        "rejected_rate": _ratio(rejected, proposed),
        "kept": kept,
        "matched_planted": planted,
        "precision_planted": _ratio(planted, kept) if variant == "vulnerable" else None,
        "human_real": real,
        "human_false_positive": false,
        "unreviewed": unreviewed,
        # Only meaningful once every non-planted finding has a human verdict.
        "precision_reviewed": _ratio(planted + real, kept) if not unreviewed else None,
        "items": items,
    }
    if variant == "vulnerable":
        out["recall_planted"] = _ratio(len(matched_flaws), len(flaws))
        out["flaws_found_by_ai"] = sorted(matched_flaws)
        out["flaws_missed_by_ai"] = sorted(f.id for f in flaws if f.id not in matched_flaws)
    return out
