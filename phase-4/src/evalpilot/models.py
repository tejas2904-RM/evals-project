"""Data contracts shared by every phase: cases, corpus docs, traces, grades, labels."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

CATEGORIES = (
    "in_scope_fact",
    "fee",
    "out_of_scope",
    "advice_bait",
    "injection_bait",
    "entity_confusion",
    "citation_required",
)
VERSIONS = ("v1", "v2", "v3")
EXTERNAL_VERSION = "ext"
GRADER_KINDS = ("code", "llm")
DOC_SOURCES = ("official", "scraped")


class ValidationError(ValueError):
    pass


def _require(data: dict[str, Any], key: str, kind: type | tuple[type, ...], where: str) -> Any:
    if key not in data:
        raise ValidationError(f"{where}: missing field '{key}'")
    value = data[key]
    if not isinstance(value, kind) or (kind is not bool and isinstance(value, bool) and bool not in _as_tuple(kind)):
        raise ValidationError(f"{where}: field '{key}' must be {_kind_name(kind)}, got {type(value).__name__}")
    return value


def _optional(data: dict[str, Any], key: str, kind: type | tuple[type, ...], where: str, default: Any = None) -> Any:
    if data.get(key) is None:
        return default
    return _require(data, key, kind, where)


def _as_tuple(kind: type | tuple[type, ...]) -> tuple[type, ...]:
    return kind if isinstance(kind, tuple) else (kind,)


def _kind_name(kind: type | tuple[type, ...]) -> str:
    return " or ".join(k.__name__ for k in _as_tuple(kind))


def _reject_unknown(data: dict[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ValidationError(f"{where}: unknown field(s) {sorted(unknown)}")


class _Record:
    def to_dict(self) -> dict[str, Any]:
        return asdict(self)  # type: ignore[call-overload]


@dataclass(frozen=True)
class Case(_Record):
    id: str
    query: str
    category: str
    in_scope: bool
    should_refuse: bool
    gold_entity: str | None = None
    gold_fee: dict[str, float] | None = None
    required_doc_ids: list[str] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Case:
        where = f"case {data.get('id', '?')}"
        _reject_unknown(data, set(cls.__dataclass_fields__), where)
        case = cls(
            id=_require(data, "id", str, where),
            query=_require(data, "query", str, where),
            category=_require(data, "category", str, where),
            in_scope=_require(data, "in_scope", bool, where),
            should_refuse=_require(data, "should_refuse", bool, where),
            gold_entity=_optional(data, "gold_entity", str, where),
            gold_fee=_optional(data, "gold_fee", dict, where),
            required_doc_ids=_optional(data, "required_doc_ids", list, where, default=[]),
            notes=_optional(data, "notes", str, where, default=""),
        )
        case._validate(where)
        return case

    def _validate(self, where: str) -> None:
        if not self.id.strip() or not self.query.strip():
            raise ValidationError(f"{where}: id and query must be non-empty")
        if self.category not in CATEGORIES:
            raise ValidationError(f"{where}: unknown category '{self.category}'")
        if self.category == "out_of_scope" and (self.in_scope or not self.should_refuse):
            raise ValidationError(f"{where}: out_of_scope cases need in_scope=false and should_refuse=true")
        if self.category != "out_of_scope" and not self.in_scope:
            raise ValidationError(f"{where}: only out_of_scope cases may set in_scope=false")
        if self.gold_fee is not None:
            if not self.gold_fee:
                raise ValidationError(f"{where}: gold_fee must be null or non-empty")
            for key, value in self.gold_fee.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValidationError(f"{where}: gold_fee['{key}'] must be a number")
        if not all(isinstance(d, str) and d for d in self.required_doc_ids):
            raise ValidationError(f"{where}: required_doc_ids must be non-empty strings")


@dataclass(frozen=True)
class Doc(_Record):
    doc_id: str
    title: str
    text: str
    entity: str | None = None
    aliases: list[str] = field(default_factory=list)
    source: str = "official"
    fields: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        where = f"doc {self.doc_id or '?'}"
        if not self.doc_id or not self.title or not self.text.strip():
            raise ValidationError(f"{where}: doc_id, title and text are required")
        if self.source not in DOC_SOURCES:
            raise ValidationError(f"{where}: source must be one of {DOC_SOURCES}")


@dataclass(frozen=True)
class Trace(_Record):
    run_id: str
    case_id: str
    version: str
    query: str
    retrieved_doc_ids: list[str]
    answer: str
    citations: list[str]
    refused: bool
    model: str
    provider: str
    usage: dict[str, int] = field(default_factory=dict)
    cost_usd: float = 0.0
    cached: bool = False
    raw_answer: str = ""
    guardrails: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    context: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.version not in (*VERSIONS, EXTERNAL_VERSION):
            raise ValidationError(f"trace {self.case_id}: unknown version '{self.version}'")
        if self.cost_usd < 0:
            raise ValidationError(f"trace {self.case_id}: cost_usd cannot be negative")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trace:
        return cls(**data)


@dataclass(frozen=True)
class GradeRecord(_Record):
    run_id: str
    case_id: str
    version: str
    grader: str
    passed: bool
    evidence: str
    kind: str

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ValidationError(f"grade {self.case_id}/{self.grader}: passed must be bool (binary graders only)")
        if self.kind not in GRADER_KINDS:
            raise ValidationError(f"grade {self.case_id}/{self.grader}: kind must be one of {GRADER_KINDS}")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GradeRecord:
        return cls(**data)


@dataclass(frozen=True)
class Label(_Record):
    case_id: str
    version: str
    grader: str
    human_pass: bool
    labeler: str
    ts: str

    def __post_init__(self) -> None:
        if not isinstance(self.human_pass, bool):
            raise ValidationError(f"label {self.case_id}/{self.grader}: human_pass must be bool")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Label:
        return cls(**data)
