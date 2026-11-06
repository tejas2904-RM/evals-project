"""Binary LLM judges. Prompts live in data/judge_prompts.md; the judge model answers {pass, reason}."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.graders.base import GraderKind, make_record, not_applicable
from evalpilot.llm import LlmClient
from evalpilot.models import EXTERNAL_VERSION, Case, GradeRecord, Trace

JUDGE_NAMES = ("judge_grounded", "judge_helpful_compliant")
PARSE_ERROR = "judge_parse_error"
MAX_CONTEXT_CHARS = 12_000

VERDICT_SCHEMA = {
    "title": "judge_verdict",
    "type": "object",
    "properties": {"pass": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["pass", "reason"],
    "additionalProperties": False,
}

_SECTION_RE = re.compile(r"^## (\w+)\n(.*?)(?=^## |\Z)", re.M | re.S)


def load_judge_prompts(path: Path) -> dict[str, str]:
    sections = {name: body.strip() for name, body in _SECTION_RE.findall(path.read_text(encoding="utf-8"))}
    prompts = {name: body for name, body in sections.items() if name.startswith("judge_")}
    if missing := [n for n in JUDGE_NAMES if n not in prompts]:
        raise ValueError(f"{path.name}: missing judge section(s) {missing}")
    return prompts


def offline_key(judge: str, trace: Trace) -> str:
    return f"j:{judge}:{trace.version}:{trace.case_id}"


def build_context(trace: Trace, kb: KnowledgeBase | None) -> str:
    if trace.context:
        text = "\n\n".join(trace.context)
    elif kb is not None and trace.retrieved_doc_ids:
        parts = []
        for doc_id in trace.retrieved_doc_ids:
            if doc_id in kb.docs:
                doc = kb.doc(doc_id)
                parts.append(f"[{doc_id}] ({doc.source})\n{doc.text}")
        text = "\n\n".join(parts)
    else:
        text = ""
    return text[:MAX_CONTEXT_CHARS] or "(no retrieved context)"


def fill(template: str, *, query: str, context: str, answer: str, in_scope: str) -> str:
    # str.format would trip over the literal JSON braces in the prompt.
    values = {"{query}": query, "{context}": context, "{answer}": answer, "{in_scope}": in_scope}
    return re.sub(r"\{(query|context|answer|in_scope)\}", lambda m: values[m.group(0)], template)


def parse_verdict(content: str) -> tuple[bool, str] | None:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("pass"), bool):
        return None
    return data["pass"], str(data.get("reason", "")).strip()[:300]


@dataclass
class LlmJudge:
    name: str
    template: str
    client: LlmClient
    run_id: str = ""
    kind: GraderKind = "llm"

    def prompt(self, case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> str:
        return fill(
            self.template,
            query=trace.query,
            context=build_context(trace, kb),
            answer=trace.answer,
            in_scope="unknown" if case is None else str(case.in_scope).lower(),
        )

    def grade(self, case: Case | None, trace: Trace, kb: KnowledgeBase | None) -> GradeRecord:
        if self.name == "judge_grounded" and trace.version == EXTERNAL_VERSION and not trace.context:
            return make_record(trace, self.name, self.kind, True,
                               not_applicable("target exposes no retrieved context (set context_jsonpath in the adapter)"))
        response = self.client.chat(
            [{"role": "user", "content": self.prompt(case, trace, kb)}],
            purpose="judge",
            run_id=self.run_id or trace.run_id,
            json_schema=VERDICT_SCHEMA,
            offline_key=offline_key(self.name, trace),
        )
        verdict = parse_verdict(response.content)
        if verdict is None:
            return make_record(trace, self.name, self.kind, False, f"{PARSE_ERROR}: {response.content[:120]!r}")
        passed, reason = verdict
        return make_record(trace, self.name, self.kind, passed, reason or ("pass" if passed else "fail"))
