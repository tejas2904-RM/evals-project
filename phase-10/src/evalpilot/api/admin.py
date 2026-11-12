"""Owner-only helpers for `evalpilot serve --admin`: adapter from the wizard, connection test, cost estimate, live playground.

None of this is reachable on a hosted service: the app only mounts these routes when admin mode is on, and admin mode
refuses to start when hosted.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from evalpilot.audit.adapters import AdapterConfig, HttpAdapter
from evalpilot.audit.redact import redact
from evalpilot.config import Settings
from evalpilot.llm import Ledger

QUESTION = "$QUESTION"
SESSION = "$SESSION"
PATH_RE = re.compile(r"^[A-Za-z_][\w\-]*(?:\.[A-Za-z_][\w\-]*|\[\d+\])*$")
HELLO = "Hi! In one sentence, what can you help me with?"
SAMPLE_CHARS = 300
# Fallback per-call costs (USD) when the ledger has no history yet; replaced by ledger averages once it does.
DEFAULT_CALL_USD = {"judge": 0.0006, "review": 0.004, "bot": 0.0002}


class AdminInputError(ValueError):
    pass


@dataclass(frozen=True)
class Target:
    url: str
    body: str
    answer_path: str

    def adapter_config(self) -> AdapterConfig:
        return AdapterConfig(url_path="", body=self.body, answer_path=self.answer_path)

    def adapter_toml(self) -> str:
        return ("[request]\nmethod = \"POST\"\nurl_path = \"\"\n"
                f"body = {json.dumps(self.body)}\n\n[response]\nanswer_jsonpath = {json.dumps(self.answer_path)}\n")


def parse_target(url: str, body_template: str, answer_path: str) -> Target:
    """Wizard fields -> adapter: `$QUESTION` / `$SESSION` in the body, a dotted path like `reply` or `data.items[0].text`."""
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise AdminInputError("endpoint URL must start with http:// or https://")
    template = (body_template or "").strip() or '{"message": "$QUESTION"}'
    if QUESTION not in template:
        raise AdminInputError("request body must contain $QUESTION where the question goes")
    try:
        json.loads(template.replace(QUESTION, "q").replace(SESSION, "s"))
    except json.JSONDecodeError as exc:
        raise AdminInputError(f"request body is not valid JSON ({exc.msg})") from exc
    path = (answer_path or "").strip() or "reply"
    if path.startswith("$"):
        path = path.lstrip("$").lstrip(".")
    if not PATH_RE.match(path):
        raise AdminInputError("answer path must look like reply, data.answer or choices[0].text")
    return Target(url=url, body=template.replace(QUESTION, "{message}").replace(SESSION, "{session_id}"),
                  answer_path="$." + path)


def connection_test(target: Target, *, timeout_s: float, client: httpx.Client | None = None) -> dict[str, Any]:
    adapter = HttpAdapter(target.url, target.adapter_config(), rate_per_s=0, timeout_s=timeout_s, client=client)
    try:
        reply = adapter.send(HELLO, "evalpilot-connection-test", throttle=False)
    finally:
        if client is None:
            adapter.close()
    sample = redact(reply.answer)[:SAMPLE_CHARS]
    ok = reply.ok and bool(reply.answer.strip())
    error = reply.error or ("" if ok else "the reply had no text at the answer path")
    return {"ok": ok, "status": reply.status, "sample_reply": sample, "latency_s": round(reply.latency_s, 3),
            "error": error}


def _avg_cost(ledger: Ledger, purpose: str) -> float:
    costs = [e.cost_usd for e in ledger.entries() if e.purpose == purpose and e.cost_usd > 0]
    return sum(costs) / len(costs) if costs else DEFAULT_CALL_USD[purpose]


def estimate(settings: Settings, ledger: Ledger, *, provider: str, engines: list[str], inputs: list[str],
             ai_review: bool, n_cases: int) -> dict[str, Any]:
    """Upper-bound OpenAI cost per engine for one audit, plus what the budget guard has left."""
    spent = ledger.total()
    paid = provider not in ("offline",) and settings.providers.get(provider) is not None and settings.providers[provider].paid
    has_url, has_code = "url" in inputs, "code" in inputs
    calls = {
        "behaviour": 2 * n_cases if ("behaviour" in engines and (has_url or "traces" in inputs)) else 0,
        "security": settings.audit.max_probes if ("security" in engines and has_url) else 0,
        "code": settings.audit.ai_review_max_files if ("code" in engines and has_code and ai_review) else 0,
        "config": 0,
    }
    unit = {"behaviour": "judge", "security": "judge", "code": "review", "config": "judge"}
    per_engine = {e: round(n * _avg_cost(ledger, unit[e]), 4) if paid else 0.0 for e, n in calls.items()}
    total = round(sum(per_engine.values()), 4)
    return {"provider": provider, "paid": paid, "per_engine": per_engine, "calls": calls, "total_usd": total,
            "spent_usd": round(spent, 4), "budget_usd": settings.budget_usd,
            "remaining_usd": round(max(0.0, settings.budget_usd - spent), 4),
            "fits_budget": spent + total <= settings.budget_usd}


def playground_live(settings: Settings, provider: str, question: str, versions: list[str]) -> dict[str, Any]:
    """Free-text question to the demo bot, live, through the normal client (cache + budget guard + ledger)."""
    from evalpilot.bot.bot import run_case
    from evalpilot.bot.corpus import KnowledgeBase
    from evalpilot.bot.retriever import retriever_for
    from evalpilot.data import load_corpus
    from evalpilot.llm import LlmClient
    from evalpilot.models import Case

    question = question.strip()
    if not question or len(question) > 500:
        raise AdminInputError("question must be 1-500 characters")
    kb = KnowledgeBase(load_corpus(settings.corpus_dir))
    client = LlmClient(settings, provider)
    case = Case(id="playground", query=question, category="playground", in_scope=True, should_refuse=False)
    answers, cost = {}, 0.0
    for v in versions:
        t = run_case(case, v, client, kb, retriever_for(v, kb, settings.top_k), run_id="playground")
        cost += t.cost_usd
        answers[v] = {"answer": t.answer, "citations": t.citations, "retrieved": t.retrieved_doc_ids,
                      "refused": t.refused, "guardrails": t.guardrails, "cached": t.cached, "grades": {}}
    return {"source": "live", "provider": provider, "query": question, "answers": answers, "cost_usd": round(cost, 6)}


def write_inputs(workdir: Path, target: Target | None, system_card_json: str | None) -> dict[str, Path]:
    """Persist wizard inputs so `Re-run audit` can replay them (runs/ is gitignored)."""
    out: dict[str, Path] = {}
    workdir.mkdir(parents=True, exist_ok=True)
    if target is not None:
        out["adapter"] = workdir / "adapter.toml"
        out["adapter"].write_text(target.adapter_toml(), encoding="utf-8")
    if system_card_json:
        out["system_card"] = workdir / "system_card.json"
        out["system_card"].write_text(system_card_json, encoding="utf-8")
    return out
