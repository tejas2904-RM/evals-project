"""Lexical BM25 retrieval (no embeddings, $0). v1/v2 use it unfiltered; v3 scopes it by entity."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass

from evalpilot.bot.corpus import Chunk, KnowledgeBase

STOPWORDS = frozenset(
    "a an and are as at be by can do does for from has have how i in is it its me my of on or our "
    "the this that to was what when where which who will with you your".split()
)
SUFFIXES = ("ing", "ed", "es", "s", "e")


def _stem(word: str) -> str:
    for suffix in SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[: -len(suffix)]
    return word


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


class BM25:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75) -> None:
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.tfs = [Counter(tokenize(f"{c.title} {c.text}")) for c in chunks]
        self.lengths = [sum(tf.values()) for tf in self.tfs]
        self.avg_len = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(term for tf in self.tfs for term in tf)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, query_terms: list[str], i: int) -> float:
        tf, length = self.tfs[i], self.lengths[i]
        total = 0.0
        for term in query_terms:
            if f := tf.get(term):
                norm = f + self.k1 * (1 - self.b + self.b * length / self.avg_len)
                total += self.idf[term] * f * (self.k1 + 1) / norm
        return total

    def top(self, query: str, k: int, allowed: set[str] | None = None) -> list[Chunk]:
        terms = tokenize(query)
        scored = [
            (self.score(terms, i), -i, chunk)
            for i, chunk in enumerate(self.chunks)
            if allowed is None or chunk.chunk_id in allowed
        ]
        scored.sort(key=lambda s: (s[0], s[1]), reverse=True)
        return [chunk for score, _, chunk in scored[:k] if score > 0]


@dataclass(frozen=True)
class Retrieval:
    chunks: list[Chunk]
    entities: list[str]

    @property
    def doc_ids(self) -> list[str]:
        ids: list[str] = []
        for chunk in self.chunks:
            if chunk.doc_id not in ids:
                ids.append(chunk.doc_id)
        return ids


class NaiveRetriever:
    """v1/v2: top-k chunks over the whole corpus, scraped content included."""

    def __init__(self, kb: KnowledgeBase, top_k: int = 4) -> None:
        self.kb, self.top_k = kb, top_k
        self.index = BM25(kb.chunks)

    def retrieve(self, query: str) -> Retrieval:
        return Retrieval(self.index.top(query, self.top_k), entities=[])


class EntityAwareRetriever:
    """v3: resolve fund names to entities, retrieve only from their official docs; never use scraped docs."""

    def __init__(self, kb: KnowledgeBase, top_k: int = 4) -> None:
        self.kb, self.top_k = kb, top_k
        self.index = BM25(kb.chunks)
        self.official = {c.chunk_id for c in kb.chunks if c.source == "official"}

    def retrieve(self, query: str) -> Retrieval:
        entities = self.kb.detect_entities(query)
        if not entities:
            return Retrieval(self.index.top(query, self.top_k, self.official), entities=[])
        # Every mentioned entity gets its own share of context, so one fund's wording can't crowd out another.
        per_entity = max(1, self.top_k // len(entities))
        chunks: list[Chunk] = []
        for entity in entities:
            ids = {c.chunk_id for c in self.kb.chunks if c.entity == entity and c.chunk_id in self.official}
            chunks += self.index.top(query, per_entity, ids) or [c for c in self.kb.chunks if c.chunk_id in ids][:per_entity]
        return Retrieval(chunks, entities)


def retriever_for(version: str, kb: KnowledgeBase, top_k: int = 4) -> NaiveRetriever | EntityAwareRetriever:
    return EntityAwareRetriever(kb, top_k) if version == "v3" else NaiveRetriever(kb, top_k)
