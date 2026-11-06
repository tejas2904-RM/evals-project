"""AI code review (judge model) with file + line evidence. Unverifiable findings never reach the register.

Source is sent only to OpenAI (paid provider) or answered from offline fixtures; other providers skip review.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from evalpilot.audit.files import SourceFile
from evalpilot.audit.models import EngineResult, Evidence, Finding
from evalpilot.audit.redact import redact
from evalpilot.llm import BudgetExceeded, LlmClient

CODE_SUFFIXES = (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rb", ".java", ".cs", ".php")
PRIORITY_NAME_RE = re.compile(r"(prompt|tool|render|output|llm|agent|chain|bot|server|app|handler|api|ingest|retriev)", re.I)
CHUNK_LINES = 400
CHARS_PER_TOKEN = 4
AI_ONLY_LIKELIHOOD = 3
OWASP_IDS = {f"LLM{i:02d}" for i in range(1, 11)}

SYSTEM_PROMPT = """You are a security reviewer for LLM applications, using the OWASP Top 10 for LLM Applications 2026:
LLM01 Prompt Injection, LLM02 Sensitive Information Disclosure, LLM03 Excessive Agency, LLM04 Supply Chain,
LLM05 Data and Model Poisoning, LLM06 Unbounded Consumption, LLM07 Misinformation, LLM08 Hidden Context Exposure,
LLM09 Vector and Embedding Weaknesses, LLM10 Improper Output Handling.

Report only concrete, exploitable issues in the code shown. For each finding give the file, the exact line range,
and an excerpt copied verbatim from those lines (no paraphrase). Likelihood and impact are integers 1-5.
If there are no issues, return {"findings": []}. Return JSON only."""

REVIEW_SCHEMA = {
    "title": "code_review",
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "owasp": {"type": "string"},
                    "title": {"type": "string"},
                    "excerpt": {"type": "string"},
                    "likelihood": {"type": "integer"},
                    "impact": {"type": "integer"},
                    "fix": {"type": "string"},
                },
                "required": ["file", "line_start", "line_end", "owasp", "title", "excerpt", "likelihood", "impact", "fix"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["findings"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Chunk:
    file: SourceFile
    start: int  # 1-based, inclusive
    end: int

    @property
    def numbered(self) -> str:
        lines = self.file.lines[self.start - 1 : self.end]
        return "\n".join(f"{n:>5}| {line}" for n, line in enumerate(lines, start=self.start))

    @property
    def key(self) -> str:
        digest = hashlib.sha256(f"{self.file.rel}\n{self.start}\n{self.numbered}".encode("utf-8")).hexdigest()[:16]
        return f"review:{digest}"

    def messages(self) -> list[dict[str, str]]:
        user = f"File: {self.file.rel} (lines {self.start}-{self.end})\n```\n{self.numbered}\n```"
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def chunk_file(file: SourceFile, size: int = CHUNK_LINES) -> list[Chunk]:
    total = len(file.lines)
    return [Chunk(file, s, min(s + size - 1, total)) for s in range(1, total + 1, size)] if total else []


def select_files(files: list[SourceFile], hit_files: list[str], max_files: int) -> list[SourceFile]:
    """Rule/tool hits first, then files whose names suggest prompt, tool or output handling."""
    by_rel = {f.rel: f for f in files}
    code = [f for f in files if f.rel.endswith(CODE_SUFFIXES) and "test" not in f.rel.lower()]
    ordered = [by_rel[r] for r in hit_files if r in by_rel and r.endswith(CODE_SUFFIXES)]
    ordered += [f for f in code if PRIORITY_NAME_RE.search(f.name) and f not in ordered]
    return ordered[:max_files]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def verify(item: dict, files: dict[str, SourceFile]) -> Evidence | None:
    """The excerpt must appear in the file's real lines line_start..line_end (whitespace-normalised)."""
    file = files.get(str(item.get("file", "")).lstrip("./"))
    start, end = item.get("line_start"), item.get("line_end")
    excerpt = _normalize(str(item.get("excerpt", "")))
    if file is None or not isinstance(start, int) or not isinstance(end, int) or not excerpt:
        return None
    if start < 1 or end < start or end > len(file.lines) or end - start > 40:
        return None
    actual = _normalize("\n".join(file.lines[start - 1 : end]))
    if excerpt not in actual:
        return None
    return Evidence(kind="file_line", location=f"{file.rel}:{start}-{end}" if end > start else f"{file.rel}:{start}",
                    excerpt=redact(excerpt)[:300])


@dataclass
class ReviewStats:
    files_reviewed: int = 0
    calls: int = 0
    findings_proposed: int = 0
    rejected: int = 0
    parse_errors: int = 0
    skipped_no_fixture: int = 0
    notes: list[str] = field(default_factory=list)


def _clamp(value: object, default: int) -> int:
    return max(1, min(5, value)) if isinstance(value, int) else default


def review(
    files: list[SourceFile],
    hit_files: list[str],
    client: LlmClient,
    *,
    audit_id: str,
    max_files: int,
    max_input_tokens: int,
    max_completion_tokens: int,
) -> EngineResult:
    result = EngineResult(engine="code")
    stats = ReviewStats()
    if not client.is_offline and not client.provider.paid:
        result.notes.append(f"AI review skipped: source is only sent to OpenAI (paid) or offline fixtures, not '{client.provider.name}'")
        result.stats = {"ai_review": vars(stats)}
        return result

    by_rel = {f.rel: f for f in files}
    budget_chars = max_input_tokens * CHARS_PER_TOKEN
    used = 0
    for file in select_files(files, hit_files, max_files):
        chunks = chunk_file(file)
        size = sum(len(c.numbered) for c in chunks)
        if used + size > budget_chars:
            stats.notes.append(f"input token cap reached before {file.rel}")
            break
        used += size
        stats.files_reviewed += 1
        for chunk in chunks:
            if client.is_offline and not client.has_offline_fixture(chunk.key):
                stats.skipped_no_fixture += 1
                continue
            try:
                response = client.chat(chunk.messages(), purpose="review", run_id=audit_id, json_schema=REVIEW_SCHEMA,
                                       offline_key=chunk.key, max_completion_tokens=max_completion_tokens)
            except BudgetExceeded as exc:
                result.notes.append(f"AI review stopped: {exc}")
                result.stats = {"ai_review": vars(stats)}
                return result
            stats.calls += 1
            try:
                items = json.loads(response.content).get("findings", [])
                assert isinstance(items, list)
            except (json.JSONDecodeError, AttributeError, AssertionError):
                stats.parse_errors += 1
                continue
            for item in items:
                stats.findings_proposed += 1
                evidence = verify(item, by_rel) if isinstance(item, dict) else None
                if evidence is None:
                    stats.rejected += 1
                    continue
                owasp = str(item.get("owasp", "")).upper()[:5]
                result.findings.append(
                    Finding(
                        engine="code",
                        check_id=f"ai-review/{owasp if owasp in OWASP_IDS else 'general'}",
                        owasp=owasp if owasp in OWASP_IDS else None,
                        title=str(item.get("title", "AI review finding"))[:160],
                        evidence=[evidence],
                        likelihood=AI_ONLY_LIKELIHOOD,
                        impact=_clamp(item.get("impact"), 3),
                        fix=str(item.get("fix", "Review and fix."))[:400],
                        merge_key=f"ai:{evidence.location}",
                        source="ai",
                    )
                )
    if stats.rejected:
        result.notes.append(f"ai_review_rejected: {stats.rejected} finding(s) dropped (excerpt didn't match the cited lines)")
    result.stats = {"ai_review": vars(stats)}
    return result


def _line_range(location: str) -> tuple[str, int, int] | None:
    m = re.match(r"^(.*):(\d+)(?:-(\d+))?$", location)
    if not m:
        return None
    start = int(m.group(2))
    return m.group(1), start, int(m.group(3) or start)


def corroborate(ai_findings: list[Finding], other: list[Finding], slack: int = 2) -> list[Finding]:
    """An AI finding that overlaps a rule/tool hit in the same file joins that risk (and raises its likelihood)."""
    anchors = []
    for f in other:
        for ev in f.evidence:
            if ev.kind == "file_line" and (loc := _line_range(ev.location)):
                anchors.append((loc, f.merge_key))
    out = []
    for f in ai_findings:
        loc = _line_range(f.evidence[0].location)
        key = f.merge_key
        if loc:
            for (rel, s, e), merge_key in anchors:
                if rel == loc[0] and s <= loc[2] + slack and loc[1] - slack <= e:
                    key = merge_key
                    break
        out.append(f.model_copy(update={"merge_key": key}))
    return out
