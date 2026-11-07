"""Draft a system card from source text only (the code is read, never imported or run; no AI).

The draft is a starting point for the owner to correct: every inferred field is listed in `notes` with its file.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Any

from evalpilot.audit.files import SourceFile
from evalpilot.audit.system_card import SystemCard

MODEL_RE = re.compile(r"""["'](gpt-[\w.\-]+|o\d[\w.\-]*|claude-[\w.\-]+|gemini-[\w.\-]+|llama[\w.\-]*|mistral[\w.\-]*)["']""")
TOOL_DEF_RE = re.compile(r"^\s*(?:async\s+)?def\s+([a-z][a-z0-9_]*)\s*\(", re.M)
TOOL_DECORATOR_RE = re.compile(r"@(?:\w+\.)?tool\b[^\n]*\n\s*(?:async\s+)?def\s+([a-z][a-z0-9_]*)", re.M)
WRITE_VERBS = ("book", "create", "update", "delete", "cancel", "send", "pay", "refund", "write", "save", "post", "submit")
EXTERNAL_HINTS = ("httpx.", "requests.", "urllib", "smtplib", "webhook")
INLINE_KEY_RE = re.compile(r"""(?i)(api[_-]?key|secret|token)\s*[:=]\s*["'][A-Za-z0-9_\-]{16,}["']""")
SCRAPE_HINTS = ("scrape", "crawl", "beautifulsoup", "bs4", "forum", "blog")
DATA_DIRS = ("data", "corpus", "docs", "knowledge", "kb")
GUARDRAIL_HINTS: dict[str, tuple[str, ...]] = {
    "input_scope_gate": ("out_of_scope", "is_out_of_scope", "off_topic", "refuse("),
    "injection_filter": ("prompt_injection", "ignore previous", "injection"),
    "pii_redaction": ("redact", "mask_pii", "scrub"),
    "output_encoding": ("html.escape", "escape(", "bleach", "sanitize"),
    "rate_limit_and_token_caps": ("rate_limit", "ratelimit", "slowapi", "max_tokens", "max_completion_tokens"),
    "citation_enforcement": ("citation", "cite"),
    "tool_confirmation": ("confirm", "requires_confirmation", "approval"),
}


def _name(files: list[SourceFile], fallback: str) -> str:
    for f in files:
        if PurePosixPath(f.rel).name.lower() in ("readme.md", "readme.txt", "readme"):
            for line in f.text.splitlines():
                if line.startswith("#"):
                    return line.lstrip("# ").strip()[:80] or fallback
    return fallback


def draft_card(files: list[SourceFile], *, fallback_name: str = "My bot") -> dict[str, Any]:
    notes: list[str] = []
    py = [f for f in files if f.rel.endswith(".py")]
    card: dict[str, Any] = {"name": _name(files, fallback_name), "purpose": "", "intended_users": ["public"]}

    models: dict[str, str] = {}
    for f in py:
        for m in MODEL_RE.findall(f.text):
            models.setdefault(m, f.rel)
    card["models"] = [{"provider": "openai" if m.startswith(("gpt", "o")) else "", "name": m} for m in sorted(models)]
    notes += [f"model {m}: {where}" for m, where in sorted(models.items())]

    tools: dict[str, dict[str, Any]] = {}
    for f in py:
        names = set(TOOL_DECORATOR_RE.findall(f.text))
        if PurePosixPath(f.rel).stem.startswith("tool"):
            names |= {n for n in TOOL_DEF_RE.findall(f.text) if not n.startswith("_")}
        for n in sorted(names):
            writes = any(n.startswith(v) or f"_{v}" in n for v in WRITE_VERBS)
            external = any(h in f.text for h in EXTERNAL_HINTS)
            side = "external" if writes and external else "write" if writes else "read"
            confirm = "confirm" in f.text.lower()
            tools.setdefault(n, {"name": n, "side_effects": side, "requires_confirmation": confirm})
            notes.append(f"tool {n} ({side}): {f.rel}")
    card["tools"] = list(tools.values())

    sources: dict[str, dict[str, Any]] = {}
    for f in files:
        parts = PurePosixPath(f.rel).parts
        if len(parts) > 1 and parts[0].lower() in DATA_DIRS:
            sources.setdefault(parts[0], {"name": parts[0], "type": "official", "ingestion": "files in repo"})
    for f in py:
        low = f.text.lower()
        if any(h in low for h in SCRAPE_HINTS):
            sources.setdefault("scraped", {"name": "scraped", "type": "scraped", "ingestion": f.rel})
            notes.append(f"scraped content: {f.rel}")
    card["data_sources"] = list(sources.values())

    declared = []
    for layer, hints in GUARDRAIL_HINTS.items():
        hit = next((f.rel for f in py if any(h in f.text.lower() for h in hints)), None)
        if hit:
            declared.append(layer)
            notes.append(f"guardrail {layer}: {hit}")
    card["guardrails_declared"] = declared

    inline = next((f.rel for f in files if INLINE_KEY_RE.search(f.text)), None)
    card["secrets_management"] = "inline" if inline else "env"
    if inline:
        notes.append(f"secret-like literal: {inline}")
    logs_prompts = next((f.rel for f in py if re.search(r"log\w*\.(info|debug|warning)\([^)]*(prompt|message|query)", f.text)), None)
    card["logging"] = {"logs_prompts": bool(logs_prompts), "pii_redaction": "pii_redaction" in declared}
    if logs_prompts:
        notes.append(f"logs prompts: {logs_prompts}")

    SystemCard.model_validate(card)
    return {"card": card, "notes": notes, "files_read": len(files)}
