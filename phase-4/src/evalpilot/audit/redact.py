"""Secret detection rules (also the gitleaks fallback) and redaction for every audit output."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class SecretRule:
    name: str
    pattern: re.Pattern[str]
    group: int = 0


SECRET_RULES: tuple[SecretRule, ...] = (
    SecretRule("openai-key", re.compile(r"\bsk-(?:proj-|svcacct-|admin-)?[A-Za-z0-9_\-]{20,}")),
    SecretRule("aws-access-key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    SecretRule("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    SecretRule("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    SecretRule("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    SecretRule(
        "generic-secret",
        re.compile(r"""(?i)\b(?:api[_-]?key|secret(?:[_-]key)?|token|passwd|password)\b["']?\s*[:=]\s*["']([^"'\s]{12,})["']"""),
        group=1,
    ),
)

_PLACEHOLDER_RE = re.compile(r"(?i)(your|example|changeme|placeholder|dummy|xxxx|<|\$\{|\{\{|os\.environ|getenv|redacted|…)")


def is_placeholder(value: str) -> bool:
    return bool(_PLACEHOLDER_RE.search(value)) or len(set(value)) <= 3


def mask(value: str) -> str:
    """`sk-…ABCD`: first 3 + last 4 characters, never the whole secret."""
    if len(value) < 12:
        return "***"
    return f"{value[:3]}…{value[-4:]}"


@dataclass(frozen=True)
class SecretMatch:
    rule: str
    start: int
    end: int
    value: str


def find_secrets(text: str) -> list[SecretMatch]:
    found: list[SecretMatch] = []
    for rule in SECRET_RULES:
        for m in rule.pattern.finditer(text):
            value = m.group(rule.group)
            if rule.name != "private-key" and is_placeholder(value):
                continue
            start, end = m.span(rule.group)
            if any(start < f.end and f.start < end for f in found):
                continue
            found.append(SecretMatch(rule.name, start, end, value))
    return sorted(found, key=lambda f: f.start)


def redact(text: str) -> str:
    if not text:
        return text
    out, last = [], 0
    for match in find_secrets(text):
        out.append(text[last : match.start])
        out.append(mask(match.value) if match.rule != "private-key" else "-----BEGIN PRIVATE KEY----- [redacted]")
        last = match.end
    out.append(text[last:])
    return "".join(out)
