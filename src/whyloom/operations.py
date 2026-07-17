from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from .config import DEFAULT_CONFIG, resolve_repository_path
from .migrations import INDEX_FORMAT_VERSION
from .models import Diagnostic
from .records import discover_records
from .store import GraphStore

OVERVIEW = """# Project overview

Describe the project mission, major subsystems, and stable boundaries here.
Keep this concise and link detailed rationale through records.
"""

GLOSSARY = """# Project glossary

Define project-specific terms and their canonical meanings here.
"""

DECISION_TEMPLATE = """---
id: DEC-XXXX
type: decision
title: Short decision title
status: proposed
date: {date}
targets: []
constraints: []
supersedes: []
---

## Context

What forced the decision.

## Decision

The selected approach.

## Rationale

Concise, reviewable reasoning.

## Alternatives

Options considered and why they were not selected.

## Consequences

Expected benefits, costs, and follow-up work.
"""

CONSTRAINT_TEMPLATE = """---
id: CON-XXXX
type: constraint
title: Short constraint title
status: proposed
date: {date}
targets: []
constraints: []
supersedes: []
---

## Constraint

The condition that must remain true.

## Evidence

Why the condition exists and where it is verified.
"""


def _write_new(path: Path, content: str, created: list[str], skipped: list[str]) -> None:
    if path.exists():
        skipped.append(path.as_posix())
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    created.append(path.as_posix())


def init_project(root: Path) -> dict:
    root = root.resolve()
    created: list[str] = []
    skipped: list[str] = []
    for directory in ("architecture", "decisions", "constraints", "incidents"):
        (root / ".whyloom" / directory).mkdir(parents=True, exist_ok=True)
    _write_new(root / ".whyloom" / "overview.md", OVERVIEW, created, skipped)
    _write_new(root / ".whyloom" / "glossary.md", GLOSSARY, created, skipped)
    _write_new(root / "whyloom.yaml", yaml.safe_dump(DEFAULT_CONFIG, sort_keys=False), created, skipped)
    today = date.today().isoformat()
    _write_new(root / ".whyloom" / "templates" / "decision.md", DECISION_TEMPLATE.format(date=today), created, skipped)
    _write_new(root / ".whyloom" / "templates" / "constraint.md", CONSTRAINT_TEMPLATE.format(date=today), created, skipped)
    ignore = root / ".gitignore"
    existing = ignore.read_text(encoding="utf-8") if ignore.exists() else ""
    lines = existing.splitlines()
    if ".whyloom/" in lines:
        migrated = [".whyloom/cache/" if line == ".whyloom/" else line for line in lines]
        ignore.write_text("\n".join(migrated) + "\n", encoding="utf-8")
        created.append(ignore.as_posix())
    elif ".whyloom/cache/" not in lines:
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        ignore.write_text(existing + prefix + ".whyloom/cache/\n", encoding="utf-8")
        created.append(ignore.as_posix())
    else:
        skipped.append(ignore.as_posix())
    return {"root": str(root), "created": created, "skipped": skipped}


def validate_project(root: Path, config: dict) -> dict:
    root = root.resolve()
    records, diagnostics = discover_records(root, config["records_dir"])
    by_id = {}
    for record in records:
        if record.id in by_id:
            diagnostics.append(Diagnostic(code="REC002", severity="error", message=f"duplicate record id {record.id}", path=record.path.as_posix()))
        by_id[record.id] = record
        for target in record.targets:
            target_path = root / target
            try:
                target_path.resolve().relative_to(root)
            except ValueError:
                diagnostics.append(Diagnostic(code="LINK003", severity="error", message=f"target resolves outside repository: {target}", path=record.path.as_posix()))
                continue
            if not target_path.exists():
                diagnostics.append(Diagnostic(code="LINK001", severity="error", message=f"target does not exist: {target}", path=record.path.as_posix()))
        for reference in [*record.constraints, *record.supersedes]:
            if reference not in {candidate.id for candidate in records}:
                diagnostics.append(Diagnostic(code="LINK002", severity="error", message=f"record reference does not exist: {reference}", path=record.path.as_posix()))
        if record.id in record.supersedes:
            diagnostics.append(Diagnostic(code="LIFE001", severity="error", message="record cannot supersede itself", path=record.path.as_posix()))

    supersession_graph = {record.id: record.supersedes for record in records}

    def has_cycle(start: str) -> bool:
        active: set[str] = set()
        visited: set[str] = set()

        def visit(identifier: str) -> bool:
            if identifier in active:
                return True
            if identifier in visited:
                return False
            active.add(identifier)
            if any(visit(neighbor) for neighbor in supersession_graph.get(identifier, [])):
                return True
            active.remove(identifier)
            visited.add(identifier)
            return False

        return visit(start)

    cyclic = sorted(identifier for identifier in supersession_graph if has_cycle(identifier))
    if cyclic:
        diagnostics.append(Diagnostic(code="LIFE002", severity="error", message=f"supersession cycle detected: {', '.join(cyclic)}"))

    accepted_constraints = [record for record in records if record.type.value == "constraint" and record.status.value in {"accepted", "implemented"}]
    by_title: dict[str, list[str]] = {}
    for record in accepted_constraints:
        by_title.setdefault(record.title.casefold(), []).append(record.id)
    for title, identifiers in by_title.items():
        if len(identifiers) > 1:
            diagnostics.append(Diagnostic(code="CONFLICT001", severity="warning", message=f"multiple active constraints share title '{title}': {', '.join(identifiers)}"))

    db_path = root / config["database"]
    if db_path.exists():
        with GraphStore(db_path, create=False) as store:
            for record in records:
                source_digest = store.source_hash(record.path.as_posix())
                if source_digest and source_digest != record.source_hash:
                    diagnostics.append(Diagnostic(code="STALE001", severity="warning", message="record changed since the last index", path=record.path.as_posix()))
    errors = [item for item in diagnostics if item.severity == "error"]
    warnings = [item for item in diagnostics if item.severity == "warning"]
    return {
        "valid": not errors,
        "records": len(records),
        "errors": [item.model_dump(mode="json") for item in errors],
        "warnings": [item.model_dump(mode="json") for item in warnings],
    }


def doctor_project(root: Path, config: dict) -> dict:
    root = root.resolve()
    database = resolve_repository_path(root, config["database"])
    validation = validate_project(root, config)
    outdated_sources = 0
    if database.is_file():
        with GraphStore(database, create=False) as store:
            outdated_sources = store.outdated_source_count(INDEX_FORMAT_VERSION)
    checks = [
        {"name": "repository", "ok": root.is_dir(), "detail": str(root)},
        {"name": "configuration", "ok": (root / "whyloom.yaml").is_file(), "detail": "whyloom.yaml"},
        {"name": "records", "ok": (root / config["records_dir"]).is_dir(), "detail": config["records_dir"]},
        {
            "name": "index",
            "ok": database.is_file() and outdated_sources == 0,
            "detail": config["database"] if outdated_sources == 0 else f"{outdated_sources} sources require reindexing",
        },
        {"name": "validation", "ok": validation["valid"], "detail": f"{validation['records']} records"},
    ]
    return {
        "ready": all(check["ok"] for check in checks),
        "root": str(root),
        "checks": checks,
        "errors": validation["errors"],
        "warnings": validation["warnings"],
    }


def reflect_project(
    root: Path,
    task_summary: str,
    diff_text: str | None = None,
    records_dir: str = ".whyloom",
) -> dict:
    root = root.resolve()
    status_text = ""
    warnings: list[str] = []
    baseline = "provided_diff" if diff_text is not None else "HEAD"
    if diff_text is None:
        try:
            has_head = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            ).returncode == 0
            baseline = "HEAD" if has_head else "none"
            if not has_head:
                warnings.append("No Git baseline exists; untracked files may represent the entire repository.")
            diff_command = ["git", "diff"]
            if has_head:
                diff_command.append("HEAD")
            diff_command.extend(["--", "."])
            diff_text = subprocess.run(
                diff_command,
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            ).stdout
            status_text = subprocess.run(
                ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            ).stdout
        except OSError:
            diff_text = ""
            baseline = "unavailable"
            warnings.append("Git is unavailable; no changed paths could be inferred.")
    changed_paths = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            changed_paths.append(line.removeprefix("+++ b/"))
    for entry in status_text.split("\0"):
        if len(entry) >= 4:
            changed_paths.append(entry[3:])
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    proposal_id = f"PROP-{stamp}"
    path = root / records_dir / "proposals" / f"{proposal_id.lower()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "id": proposal_id,
        "type": "decision",
        "title": f"Review learning from: {task_summary[:72]}",
        "status": "proposed",
        "date": date.today().isoformat(),
        "targets": sorted(set(changed_paths)),
        "constraints": [],
        "supersedes": [],
    }
    body = (
        "---\n"
        + yaml.safe_dump(metadata, sort_keys=False)
        + "---\n\n## Context\n\n"
        + task_summary.strip()
        + "\n\n## Proposed learning\n\nReview the task and diff, then replace this text with concise project rationale.\n"
        + "\n## Evidence\n\n"
        + ("\n".join(f"- `{item}`" for item in sorted(set(changed_paths))) or "- No changed paths were detected.")
        + "\n"
    )
    path.write_text(body, encoding="utf-8")
    return {
        "proposal": path.relative_to(root).as_posix(),
        "status": "proposed",
        "changed_paths": sorted(set(changed_paths)),
        "requires_review": True,
        "baseline": baseline,
        "warnings": warnings,
    }


def format_human(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)
