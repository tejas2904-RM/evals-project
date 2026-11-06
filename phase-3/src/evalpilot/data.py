"""Load the eval set and the fictional fund-house corpus."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from evalpilot.models import Case, Doc, ValidationError
from evalpilot.store import read_jsonl

FEE_PREFIX = "fee."


def load_cases(path: Path) -> list[Case]:
    cases = read_jsonl(path, Case.from_dict)
    seen: set[str] = set()
    for case in cases:
        if case.id in seen:
            raise ValidationError(f"{path.name}: duplicate case id '{case.id}'")
        seen.add(case.id)
    return cases


def parse_doc(text: str, filename: str = "<doc>") -> Doc:
    """Parse a corpus markdown file with a `---` front-matter block of `key: value` lines."""
    lines = text.lstrip("\ufeff").splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValidationError(f"{filename}: missing front-matter")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        raise ValidationError(f"{filename}: unterminated front-matter") from None

    meta: dict[str, str] = {}
    fields: dict[str, float] = {}
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        if ":" not in raw:
            raise ValidationError(f"{filename}: bad front-matter line '{raw}'")
        key, value = (part.strip() for part in raw.split(":", 1))
        if key.startswith(FEE_PREFIX):
            try:
                fields[key.removeprefix(FEE_PREFIX)] = float(value)
            except ValueError:
                raise ValidationError(f"{filename}: '{key}' must be numeric") from None
        else:
            meta[key] = value

    return Doc(
        doc_id=meta.get("doc_id", ""),
        title=meta.get("title", ""),
        text="\n".join(lines[end + 1 :]).strip(),
        entity=meta.get("entity") or None,
        aliases=[a.strip() for a in meta.get("aliases", "").split(",") if a.strip()],
        source=meta.get("source", "official"),
        fields=fields,
    )


def load_corpus(corpus_dir: Path) -> list[Doc]:
    docs = [parse_doc(p.read_text(encoding="utf-8"), p.name) for p in sorted(corpus_dir.glob("*.md"))]
    if not docs:
        raise ValidationError(f"{corpus_dir}: no corpus documents found")
    ids = [d.doc_id for d in docs]
    if len(ids) != len(set(ids)):
        raise ValidationError(f"{corpus_dir}: duplicate doc_id values")
    return docs


@dataclass(frozen=True)
class Dataset:
    cases: list[Case]
    docs: list[Doc]

    @property
    def doc_ids(self) -> set[str]:
        return {d.doc_id for d in self.docs}

    @property
    def entities(self) -> set[str]:
        return {d.entity for d in self.docs if d.entity}

    def alias_map(self) -> dict[str, str]:
        """alias (lower-cased) -> entity, from official docs only."""
        return {
            alias.lower(): doc.entity
            for doc in self.docs
            if doc.entity and doc.source == "official"
            for alias in doc.aliases
        }

    def check_references(self) -> list[str]:
        problems: list[str] = []
        doc_ids, entities = self.doc_ids, self.entities
        for case in self.cases:
            for doc_id in case.required_doc_ids:
                if doc_id not in doc_ids:
                    problems.append(f"{case.id}: required doc '{doc_id}' not in corpus")
            if case.gold_entity and case.gold_entity not in entities:
                problems.append(f"{case.id}: gold_entity '{case.gold_entity}' not in corpus")
            if case.gold_entity and case.gold_fee:
                official = [d for d in self.docs if d.entity == case.gold_entity and d.source == "official"]
                for key, value in case.gold_fee.items():
                    if not any(d.fields.get(key) == value for d in official):
                        problems.append(f"{case.id}: gold_fee {key}={value} not found in {case.gold_entity} docs")
        return problems


def load_dataset(cases_path: Path, corpus_dir: Path) -> Dataset:
    dataset = Dataset(cases=load_cases(cases_path), docs=load_corpus(corpus_dir))
    if problems := dataset.check_references():
        raise ValidationError("Dataset reference errors:\n  " + "\n  ".join(problems))
    return dataset
