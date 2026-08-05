from __future__ import annotations

import re
from datetime import date as Date
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class RecordType(StrEnum):
    DECISION = "decision"
    CONSTRAINT = "constraint"
    ARCHITECTURE = "architecture"
    INCIDENT = "incident"
    GLOSSARY = "glossary"


class RecordStatus(StrEnum):
    # OKF lifecycle values (canonical).
    DRAFT = "draft"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    # Legacy whyloom values, still parsed and mapped forward for compatibility.
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IMPLEMENTED = "implemented"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    EXPIRED = "expired"


# A record is authoritative (governs) when its lifecycle is stable/accepted.
GOVERNING_STATUSES = {RecordStatus.STABLE, RecordStatus.ACCEPTED, RecordStatus.IMPLEMENTED}

# Legacy → OKF status mapping. Applied when reading and when writing forward.
LEGACY_STATUS_MAP = {
    RecordStatus.PROPOSED: RecordStatus.DRAFT,
    RecordStatus.ACCEPTED: RecordStatus.STABLE,
    RecordStatus.IMPLEMENTED: RecordStatus.STABLE,
    RecordStatus.SUPERSEDED: RecordStatus.DEPRECATED,
    RecordStatus.REJECTED: RecordStatus.DEPRECATED,
    RecordStatus.EXPIRED: RecordStatus.DEPRECATED,
}


def okf_status(status: RecordStatus) -> RecordStatus:
    """Normalize any lifecycle value to its OKF canonical form."""
    return LEGACY_STATUS_MAP.get(status, status)


class InferenceConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def _validate_actor(value: str) -> str:
    """OKF actor convention: `<producer>/<version>` for an agent, `human:<id>` for
    a person, `process:<id>` for an automated process. We accept any non-empty
    string but normalize whitespace, so producers are not blocked by a strict
    grammar while the common forms round-trip cleanly."""
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("actor must not be empty")
    return normalized


class Generated(BaseModel):
    """OKF: how the current content was produced."""

    by: str
    at: str | None = None

    @field_validator("by")
    @classmethod
    def _actor(cls, value: str) -> str:
        return _validate_actor(value)

    def is_human(self) -> bool:
        return self.by.startswith("human:")


class Verified(BaseModel):
    """OKF: a single confirmation that the content was reviewed."""

    by: str
    at: str | None = None

    @field_validator("by")
    @classmethod
    def _actor(cls, value: str) -> str:
        return _validate_actor(value)

    def is_human(self) -> bool:
        return self.by.startswith("human:")


class RecordEvidence(BaseModel):
    kind: str
    source: str
    summary: str

    @field_validator("kind", "source", "summary")
    @classmethod
    def bounded_text(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("evidence fields must not be empty")
        if len(normalized) > 500:
            raise ValueError("evidence fields must be at most 500 characters")
        return normalized


class ProjectRecord(BaseModel):
    id: str
    type: RecordType
    title: str
    status: RecordStatus
    date: Date | None = None
    targets: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    supersedes: list[str] = Field(default_factory=list)
    confidence: InferenceConfidence | None = None
    evidence: list[RecordEvidence] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    # OKF trust family: who produced this content, and who has verified it.
    generated: Generated | None = None
    verified: list[Verified] = Field(default_factory=list)
    body: str = ""
    path: Path
    source_hash: str

    @field_validator("verified", mode="before")
    @classmethod
    def _coerce_verified(cls, value: Any) -> Any:
        # OKF allows a single verifier as one {by, at} mapping without a list dash.
        if isinstance(value, dict):
            return [value]
        return value

    def okf_status(self) -> RecordStatus:
        return okf_status(self.status)

    def human_verified(self) -> bool:
        """True when at least one human has verified this record — the review gate."""
        return any(v.is_human() for v in self.verified)

    def looks_agent_generated(self) -> bool:
        """Whether the current content was produced by a non-human. Prefers the
        explicit OKF `generated.by`; falls back to the legacy signals (an INFERRED
        id or a machine confidence score) for records written before OKF fields."""
        if self.generated is not None:
            return not self.generated.is_human()
        return "INFERRED" in self.id.upper() or self.confidence is not None

    @field_validator("id")
    @classmethod
    def stable_id(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]*", value):
            raise ValueError("record id must match [A-Z][A-Z0-9_-]*")
        return value

    @field_validator("targets")
    @classmethod
    def normalized_targets(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for value in values:
            candidate = value.replace("\\", "/").strip()
            path = PurePosixPath(candidate)
            if not candidate or path.is_absolute() or ".." in path.parts:
                raise ValueError("targets must be repository-relative paths without '..'")
            normalized.append(path.as_posix().removeprefix("./"))
        return normalized

    @field_validator("constraints", "supersedes")
    @classmethod
    def normalized_record_references(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values]
        if any(not re.fullmatch(r"[A-Z][A-Z0-9_-]*", value) for value in normalized):
            raise ValueError("record references must use stable record ids")
        return normalized

    @field_validator("open_questions")
    @classmethod
    def normalized_questions(cls, values: list[str]) -> list[str]:
        questions = [" ".join(value.split()) for value in values]
        if any(not value or len(value) > 500 for value in questions):
            raise ValueError("open questions must contain 1 to 500 characters")
        return questions


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    path: str | None = None
    source_path: str
    source_hash: str
    data: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    origin: str
    evidence: str
    provenance: Literal["EXTRACTED", "INFERRED", "AMBIGUOUS"] = "EXTRACTED"
    confidence: float = 1.0
    source_path: str
    source_hash: str


class Diagnostic(BaseModel):
    code: str
    severity: str
    message: str
    path: str | None = None
