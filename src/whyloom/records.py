from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from pydantic import ValidationError

from .models import Diagnostic, ProjectRecord


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def record_sections(body: str) -> dict[str, str]:
    """Split a record body into ``{heading_casefold: text}`` for its ``## Heading``
    blocks, so renderers can pull Context/Decision/Consequences without re-parsing.
    Keys are casefolded; ``<!-- ... -->`` placeholder-only bodies collapse to ''."""
    sections: dict[str, str] = {}
    heading: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        if heading is None:
            return
        text = "\n".join(buffer).strip()
        # Drop agent/HTML-comment scaffolding so an unfilled section reads as empty.
        if text.startswith("<!--") and text.endswith("-->"):
            text = ""
        sections[heading.casefold()] = text

    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            heading = line[3:].strip()
            buffer = []
        elif heading is not None:
            buffer.append(line)
    flush()
    return sections


def parse_record(path: Path, root: Path) -> ProjectRecord:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError("record must start with YAML frontmatter")
    try:
        _, frontmatter, body = text.split("---", 2)
    except ValueError as exc:
        raise ValueError("record frontmatter is not closed") from exc
    metadata = yaml.safe_load(frontmatter) or {}
    return ProjectRecord(
        **metadata,
        body=body.strip(),
        path=path.relative_to(root),
        source_hash=sha256_text(text),
    )


def discover_records(root: Path, records_dir: str = ".whyloom") -> tuple[list[ProjectRecord], list[Diagnostic]]:
    records: list[ProjectRecord] = []
    diagnostics: list[Diagnostic] = []
    base = root / records_dir
    try:
        base.resolve().relative_to(root.resolve())
    except ValueError:
        diagnostics.append(
            Diagnostic(code="REC003", severity="error", message="records directory resolves outside repository", path=records_dir)
        )
        return records, diagnostics
    if not base.exists():
        return records, diagnostics
    for path in sorted(base.rglob("*.md")):
        relative = path.relative_to(base)
        if relative.parts and relative.parts[0] in {"cache", "templates"}:
            continue
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        try:
            records.append(parse_record(path, root))
        except (ValueError, ValidationError, yaml.YAMLError) as exc:
            diagnostics.append(
                Diagnostic(
                    code="REC001",
                    severity="error",
                    message=str(exc),
                    path=str(path.relative_to(root)),
                )
            )
    return records, diagnostics
