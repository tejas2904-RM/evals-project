"""Chunked corpus with an entity alias index."""

from __future__ import annotations

import re
from dataclasses import dataclass

from evalpilot.models import Doc


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    title: str
    text: str
    entity: str | None
    source: str


def chunk_doc(doc: Doc) -> list[Chunk]:
    """Split on `## ` headings; the title travels with every chunk so fund names stay matchable."""
    sections = re.split(r"(?m)^(?=## )", doc.text)
    return [
        Chunk(f"{doc.doc_id}#{i}", doc.doc_id, doc.title, section.strip(), doc.entity, doc.source)
        for i, section in enumerate(s for s in sections if s.strip())
    ]


class KnowledgeBase:
    def __init__(self, docs: list[Doc]) -> None:
        self.docs = {d.doc_id: d for d in docs}
        self.chunks = [chunk for doc in docs for chunk in chunk_doc(doc)]
        self.entity_names: dict[str, str] = {}
        aliases: dict[str, str] = {}
        for doc in docs:
            if doc.entity and doc.source == "official":
                for alias in doc.aliases:
                    aliases[alias.lower()] = doc.entity
                if doc.aliases:
                    self.entity_names[doc.entity] = doc.aliases[0]
        # Longest alias first so "Bluechip Value Fund" wins over any shorter overlapping alias.
        self._aliases = sorted(aliases.items(), key=lambda kv: -len(kv[0]))
        self._alias_res = [(re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE), e) for a, e in self._aliases]

    @property
    def aliases(self) -> dict[str, str]:
        return dict(self._aliases)

    def detect_entities(self, text: str) -> list[str]:
        """Entities mentioned in text, in order of appearance, using longest non-overlapping alias matches."""
        taken: list[tuple[int, int]] = []
        found: list[tuple[int, str]] = []
        for pattern, entity in self._alias_res:
            for m in pattern.finditer(text):
                if any(m.start() < end and start < m.end() for start, end in taken):
                    continue
                taken.append((m.start(), m.end()))
                found.append((m.start(), entity))
        ordered: list[str] = []
        for _, entity in sorted(found):
            if entity not in ordered:
                ordered.append(entity)
        return ordered

    def doc(self, doc_id: str) -> Doc:
        return self.docs[doc_id]
