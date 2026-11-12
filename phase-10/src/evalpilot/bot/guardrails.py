"""Deterministic v2/v3 guardrails (G1-G4). G5/G6 live in the v3 retriever. No extra LLM calls."""

from __future__ import annotations

import re

from evalpilot.bot.corpus import Chunk, KnowledgeBase
from evalpilot.bot.retriever import tokenize
from evalpilot.patterns import (
    CITATION_RE,
    DOMAIN_RE,
    OOS_TOPIC_RE,
    find_advice,
    find_unsafe_claim,
    looks_like_refusal,
    parse_citations,
    split_sentences,
)

REFUSAL = "I can only answer questions about our mutual fund schemes, fees and documents. I can't help with that."
ADVICE_REPLACEMENT = (
    "I can't recommend or rank specific funds, and the right choice depends on your goals and risk profile. "
    "Each scheme's objective, risk level and costs are in its factsheet, and a SEBI-registered investment "
    "advisor can help you decide."
)
UNSAFE_DISCLAIMER = "Mutual fund returns are not guaranteed and are subject to market risk."


def is_out_of_scope(query: str, kb: KnowledgeBase) -> bool:
    """G1. In scope if a fund is named or a fund-domain term appears and no off-topic subject dominates."""
    if kb.detect_entities(query):
        return False
    has_domain = bool(DOMAIN_RE.search(query))
    if OOS_TOPIC_RE.search(query) and "asterion" not in query.lower():
        return True
    return not has_domain


def apply_advice_filter(answer: str) -> tuple[str, bool]:
    """G2. Replace any recommendation with a compliant non-recommendation."""
    if find_advice(answer):
        return ADVICE_REPLACEMENT, True
    return answer, False


def apply_unsafe_filter(answer: str) -> tuple[str, bool]:
    """G3. Drop sentences making guarantee / risk-free claims; add a disclaimer when anything was removed."""
    sentences = split_sentences(answer)
    kept = [s for s in sentences if not find_unsafe_claim(s)]
    if len(kept) == len(sentences):
        return answer, False
    kept.append(UNSAFE_DISCLAIMER)
    return " ".join(kept), True


def ensure_citations(answer: str, chunks: list[Chunk]) -> tuple[str, bool]:
    """G4. Remove citations to documents that weren't retrieved; append sources if none remain."""
    retrieved = {c.doc_id for c in chunks}
    changed = False

    def keep_or_drop(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group(1) in retrieved:
            return match.group(0)
        changed = True
        return ""

    cleaned = re.sub(r"\s{2,}", " ", CITATION_RE.sub(keep_or_drop, answer)).strip()
    cleaned = re.sub(r"\s+([.,;])", r"\1", cleaned)
    if looks_like_refusal(cleaned) or parse_citations(cleaned) or not chunks:
        return cleaned, changed

    sources = _best_sources(cleaned, chunks)
    if not sources:
        return cleaned, changed
    return f"{cleaned} Sources: {' '.join(f'[{d}]' for d in sources)}", True


def _best_sources(answer: str, chunks: list[Chunk], k: int = 2) -> list[str]:
    answer_terms = set(tokenize(answer))
    overlap: dict[str, int] = {}
    official: dict[str, bool] = {}
    for chunk in chunks:
        score = len(answer_terms & set(tokenize(f"{chunk.title} {chunk.text}")))
        overlap[chunk.doc_id] = max(overlap.get(chunk.doc_id, 0), score)
        official[chunk.doc_id] = chunk.source == "official"
    ranked = sorted(overlap, key=lambda d: (official[d], overlap[d]), reverse=True)
    return [d for d in ranked if official[d] and overlap[d] > 0][:k]


def apply_output_guardrails(answer: str, chunks: list[Chunk]) -> tuple[str, list[str]]:
    applied: list[str] = []
    answer, hit = apply_advice_filter(answer)
    if hit:
        applied.append("advice_filter")
    answer, hit = apply_unsafe_filter(answer)
    if hit:
        applied.append("unsafe_filter")
    answer, hit = ensure_citations(answer, chunks)
    if hit:
        applied.append("citation_fix")
    return answer, applied
