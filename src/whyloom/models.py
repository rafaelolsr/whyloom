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
    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    IMPLEMENTED = "implemented"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    EXPIRED = "expired"


GOVERNING_STATUSES = {RecordStatus.ACCEPTED, RecordStatus.IMPLEMENTED}


class InferenceConfidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


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
    body: str = ""
    path: Path
    source_hash: str

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
