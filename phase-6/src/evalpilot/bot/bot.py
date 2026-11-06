"""run_case(case, version) -> Trace: retrieve -> prompt -> LLM -> guardrails (v2/v3) -> Trace."""

from __future__ import annotations

from evalpilot.bot.corpus import KnowledgeBase
from evalpilot.bot.guardrails import REFUSAL, apply_output_guardrails, is_out_of_scope
from evalpilot.bot.prompts import build_messages
from evalpilot.bot.retriever import EntityAwareRetriever, NaiveRetriever
from evalpilot.llm import LlmClient
from evalpilot.models import Case, Trace
from evalpilot.patterns import looks_like_refusal, parse_citations

GUARDED_VERSIONS = ("v2", "v3")


def offline_key(version: str, case_id: str) -> str:
    return f"{version}:{case_id}"


def run_case(
    case: Case,
    version: str,
    client: LlmClient,
    kb: KnowledgeBase,
    retriever: NaiveRetriever | EntityAwareRetriever,
    run_id: str,
) -> Trace:
    guarded = version in GUARDED_VERSIONS
    base = dict(run_id=run_id, case_id=case.id, version=version, query=case.query, provider=client.provider.name)

    if guarded and is_out_of_scope(case.query, kb):
        return Trace(
            **base,
            retrieved_doc_ids=[],
            answer=REFUSAL,
            citations=[],
            refused=True,
            model="guardrail",
            guardrails=["scope_gate"],
        )

    retrieval = retriever.retrieve(case.query)
    entity_names = [kb.entity_names.get(e, e) for e in retrieval.entities]
    messages = build_messages(version, case.query, retrieval.chunks, entity_names)
    response = client.chat(messages, purpose="bot", run_id=run_id, offline_key=offline_key(version, case.id))

    raw = response.content.strip()
    answer, applied = apply_output_guardrails(raw, retrieval.chunks) if guarded else (raw, [])

    return Trace(
        **base,
        retrieved_doc_ids=retrieval.doc_ids,
        answer=answer,
        citations=parse_citations(answer),
        refused=looks_like_refusal(answer),
        model=response.model,
        usage=response.usage.model_dump(),
        cost_usd=response.cost_usd,
        cached=response.cached,
        raw_answer=raw,
        guardrails=applied,
        entities=retrieval.entities,
    )
