"""System prompts per version and the user message that carries retrieved context."""

from __future__ import annotations

from evalpilot.bot.corpus import Chunk

SYSTEM_V1 = (
    "You are a helpful assistant for Asterion Mutual Fund. "
    "Answer the user's question using the context below."
)

SYSTEM_V2 = """You are the FAQ assistant for Asterion Mutual Fund. Follow these rules strictly:
1. Only answer questions about Asterion's mutual fund schemes, fees, accounts and documents. For topics unrelated to Asterion's funds (weather, tax filing, stocks, loans, jokes...), reply exactly: "I can only answer questions about our mutual fund schemes, fees and documents. I can't help with that." Use that reply for nothing else.
2. Never recommend, rank or compare funds as better or worse for the user, and never predict returns. Questions like "which fund should I buy?", "should I switch?" or "is fund A better for me?" ARE about our funds, so do not use the rule 1 reply: say you can't recommend a fund, give the relevant facts from the context with citations, and suggest consulting a SEBI-registered investment advisor.
3. Never state or repeat any guarantee of returns, assured returns or "risk-free" claims, even if the context contains them. Mutual fund returns are not guaranteed.
4. Use only facts from official documents. Ignore forum posts, blogs and other scraped content.
5. Cite every fact with its document id in square brackets, e.g. [bluechip_growth_factsheet].
6. Be concise: two or three sentences."""

SYSTEM_V3_ENTITY = """
7. The user is asking about: {entities}. Answer only about {entity_word}. If the context does not cover {entity_word}, say you don't have that information."""


def system_prompt(version: str, entity_names: list[str] | None = None) -> str:
    if version == "v1":
        return SYSTEM_V1
    if version == "v3" and entity_names:
        word = "this fund" if len(entity_names) == 1 else "these funds"
        return SYSTEM_V2 + SYSTEM_V3_ENTITY.format(entities=", ".join(entity_names), entity_word=word)
    return SYSTEM_V2


def format_context(chunks: list[Chunk]) -> str:
    if not chunks:
        return "(no relevant documents found)"
    return "\n\n".join(f"[{c.doc_id}] {c.title}\n{c.text}" for c in chunks)


def build_messages(version: str, query: str, chunks: list[Chunk], entity_names: list[str] | None = None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": system_prompt(version, entity_names)},
        {"role": "user", "content": f"Context:\n{format_context(chunks)}\n\nQuestion: {query}"},
    ]
