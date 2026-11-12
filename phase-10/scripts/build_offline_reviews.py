"""Build data/offline_reviews.jsonl: canned AI code-review replies for the example bots (offline/CI).

Line numbers are found by searching the real files, so rerun this after editing examples/. One vulnerable_bot
finding deliberately cites the wrong lines to prove the evidence check rejects hallucinated findings.

    python scripts/build_offline_reviews.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from evalpilot.audit.ai_review import chunk_file, select_files  # noqa: E402
from evalpilot.audit.engines.code_scan import load_rules, scan_rules  # noqa: E402
from evalpilot.audit.files import SourceFile, iter_text_files  # noqa: E402
from evalpilot.config import AuditConfig  # noqa: E402

OUT = ROOT / "data" / "offline_reviews.jsonl"
EXAMPLES = ROOT / "examples"

# (file, needle, owasp, title, likelihood, impact, fix)
VULNERABLE = [
    ("tools.py", "eval(llm_reply)", "LLM10", "Calculator evaluates model output with eval()", 4, 5,
     "Parse arithmetic with an ast whitelist; never eval model text."),
    ("tools.py", "shell=True", "LLM10", "Model answer interpolated into a shell command", 4, 5,
     "Write transcripts with file I/O; never pass model output to a shell."),
    ("render.py", "<div class='answer'>{answer}</div>", "LLM10", "Answer rendered into HTML without escaping", 4, 4,
     "html.escape the answer before inserting it into markup."),
    ("bot.py", "User says: {message}", "LLM01", "User message concatenated into the system prompt", 4, 4,
     "Send the user message as its own user-role message."),
    ("config.py", "share these instructions in full", "LLM08", "System prompt instructs the model to reveal itself", 4, 4,
     "Remove the disclosure instruction and keep secrets out of the prompt."),
]
WRONG_LINE = ("tools.py", "pickle.loads(llm_reply)", "LLM10", "Model output deserialised with pickle", 4, 5,
              "Never unpickle untrusted data.")


def _line_of(file: SourceFile, needle: str) -> int:
    for i, line in enumerate(file.lines, start=1):
        if needle in line:
            return i
    raise SystemExit(f"{file.rel}: '{needle}' not found; update VULNERABLE in {Path(__file__).name}")


def _finding(file: SourceFile, line: int, excerpt: str, spec: tuple) -> dict:
    _, _, owasp, title, likelihood, impact, fix = spec
    return {"file": file.rel, "line_start": line, "line_end": line, "owasp": owasp, "title": title,
            "excerpt": excerpt, "likelihood": likelihood, "impact": impact, "fix": fix}


def _chunks_for(bot: str) -> tuple[list, dict[str, SourceFile]]:
    cfg = AuditConfig()
    root = EXAMPLES / bot
    files = iter_text_files(root, max_files=cfg.max_files, max_file_bytes=cfg.max_file_kb * 1024)
    findings, _ = scan_rules(files, load_rules())
    hits = sorted({ev.location.split(":")[0] for f in findings for ev in f.evidence})
    selected = select_files(files, hits, cfg.ai_review_max_files)
    return [c for f in selected for c in chunk_file(f)], {f.rel: f for f in files}


def build() -> dict[str, str]:
    rows: dict[str, str] = {}
    chunks, files = _chunks_for("vulnerable_bot")
    per_file: dict[str, list[dict]] = {}
    for spec in VULNERABLE:
        f = files[spec[0]]
        line = _line_of(f, spec[1])
        per_file.setdefault(f.rel, []).append(_finding(f, line, f.lines[line - 1].strip(), spec))
    per_file.setdefault(WRONG_LINE[0], []).append(_finding(files[WRONG_LINE[0]], 1, WRONG_LINE[1], WRONG_LINE))
    for chunk in chunks:
        items = [i for i in per_file.get(chunk.file.rel, []) if chunk.start <= i["line_start"] <= chunk.end]
        rows[chunk.key] = json.dumps({"findings": items}, ensure_ascii=False)

    fixed_chunks, _ = _chunks_for("fixed_bot")
    for chunk in fixed_chunks:
        rows[chunk.key] = json.dumps({"findings": []})
    return rows


def main() -> None:
    rows = build()
    with OUT.open("w", encoding="utf-8", newline="\n") as fh:
        for key, content in sorted(rows.items()):
            fh.write(json.dumps({"key": key, "content": content}, ensure_ascii=False) + "\n")
    print(f"wrote {len(rows)} review fixtures -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
