from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from .codegraph import source_hash as compute_source_hash
from .config import DEFAULT_CONFIG, resolve_repository_path
from .indexer import discover_code_paths
from .migrations import INDEX_FORMAT_VERSION
from .models import Diagnostic
from .records import discover_records
from .store import CorruptIndexError, GraphStore

# Whyloom-managed scaffolding is never the subject of a learning; excluding it
# keeps reflect targets focused on the code and records that actually changed.
_REFLECT_TARGET_NOISE = (".whyloom/templates/", ".whyloom/overview.md", ".whyloom/glossary.md", ".gitignore")


def learnings_report(root: Path, config: dict, changed_only: bool = False) -> dict:
    """Report the state of the retro-feed loop so capture is reliable, not
    best-effort: pending proposals awaiting human review, and source files that
    carry no governing record (rationale gaps an agent should consider filling).

    With changed_only, gaps are limited to files changed since the last index
    (Git if available, else filesystem hashes), which is what a post-work agent
    should reflect on."""
    root = root.resolve()
    database = _index_path(root, config)
    proposals_dir = root / config["records_dir"] / "proposals"
    proposals = sorted(p.relative_to(root).as_posix() for p in proposals_dir.glob("*.md")) if proposals_dir.is_dir() else []

    if not database.is_file():
        return {"proposals": proposals, "uncovered": [], "changed_only": changed_only, "index_present": False}

    with GraphStore(database, create=False) as store:
        # Files that have an incoming governing edge are "covered".
        covered = {
            row["target"].removeprefix("file:")
            for row in store.connection.execute(
                "SELECT DISTINCT target FROM edges WHERE type IN ('APPLIES_TO', 'IMPLEMENTS', 'CONSTRAINED_BY') AND target LIKE 'file:%'"
            )
        }
        # Only language-source files carry logic worth explaining; configuration
        # and generated files are not rationale gaps.
        from .languages import default_registry

        code_suffixes = default_registry().code_suffixes
        source_files = {
            row["path"]
            for row in store.connection.execute(
                "SELECT DISTINCT path FROM nodes WHERE type = 'File' AND path IS NOT NULL"
            )
            if any(row["path"].endswith(suffix) for suffix in code_suffixes)
        }
        if changed_only:
            changed, _, _ = _git_changed_paths(root)
            if not changed:
                changed, _ = _filesystem_changed_paths(root, config)
            scope = set(changed)
            source_files = {path for path in source_files if path in scope}

    uncovered = sorted(path for path in source_files if path not in covered)
    return {
        "proposals": proposals,
        "proposal_count": len(proposals),
        "uncovered": uncovered,
        "uncovered_count": len(uncovered),
        "changed_only": changed_only,
        "index_present": True,
        "next_action": (
            "Review pending proposals and run 'whyloom reflect' for significant uncovered changes."
            if proposals or uncovered
            else "Project memory is covered; no pending capture."
        ),
    }


_PROPOSABLE_TAGS = {"WHY", "DECISION", "HACK"}


def _index_path(root: Path, config: dict) -> Path:
    return resolve_repository_path(root, config["database"])


def _render_record_markdown(metadata: dict, sections: list[tuple[str, str]], preamble: str = "") -> str:
    """Render a record/proposal file: YAML front matter, an optional HTML-comment
    preamble, then ``## Heading`` blocks in the given order. Shared by reflect and
    propose so their proposal formats cannot drift."""
    parts = ["---\n", yaml.safe_dump(metadata, sort_keys=False), "---\n\n"]
    if preamble:
        parts.append(preamble.rstrip("\n") + "\n\n")
    parts.extend(f"## {heading}\n\n{body.rstrip(chr(10))}\n\n" for heading, body in sections)
    return "".join(parts).rstrip("\n") + "\n"


def propose_from_rationale(root: Path, config: dict, *, limit: int = 50) -> dict:
    """Turn high-signal in-code rationale (WHY/DECISION/HACK comments) into
    reviewable proposed decision records, so a freshly onboarded repo has
    queryable rationale on day one.

    Deterministic and offline: it only restates what the author already wrote in
    a comment. Records land as status: proposed and are never accepted
    automatically — a human still reviews before they become authoritative."""
    root = root.resolve()
    database = _index_path(root, config)
    if not database.is_file():
        return {"created": [], "skipped": 0, "reason": "no index; run whyloom index first"}

    proposals_dir = root / config["records_dir"] / "proposals"
    existing = {p.name for p in proposals_dir.glob("*.md")} if proposals_dir.is_dir() else set()

    # Gather proposable rationale grouped by the file it annotates.
    by_file: dict[str, list[dict]] = {}
    with GraphStore(database, create=False) as store:
        rows = store.connection.execute(
            "SELECT id, path, data FROM nodes WHERE type = 'Rationale'"
        ).fetchall()
    for row in rows:
        data = json.loads(row["data"])
        if data.get("tag") not in _PROPOSABLE_TAGS:
            continue
        by_file.setdefault(row["path"], []).append({"tag": data.get("tag"), "note": data.get("note"), "line": data.get("line")})

    created: list[str] = []
    skipped = 0
    proposals_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(by_file):
        if len(created) >= limit:
            break
        notes = sorted(by_file[path], key=lambda n: n.get("line") or 0)
        # Stable, path-derived id so re-running onboard does not duplicate.
        slug = re.sub(r"[^a-z0-9]+", "-", path.casefold()).strip("-")
        filename = f"prop-rationale-{slug}.md"
        if filename in existing:
            skipped += 1
            continue
        headline = notes[0]["note"][:72] if notes[0].get("note") else path
        evidence = "\n".join(f"- `{path}:{n['line']}` — {n['tag']}: {n['note']}" for n in notes)
        body = _render_record_markdown(
            {
                "id": f"PROP-RATIONALE-{slug[:40]}",
                "type": "decision",
                "title": f"Recorded rationale in {path}: {headline}",
                "status": "proposed",
                "date": date.today().isoformat(),
                "targets": [path],
                "constraints": [],
                "supersedes": [],
            },
            [
                ("Context", f"The author left rationale comments in `{path}`. They are captured here for review."),
                ("Decision", "<!-- Restate the decision these comments imply, then accept. -->"),
                ("Rationale", evidence),
                ("Alternatives", "<!-- If the comments name rejected options, record them. -->"),
                ("Consequences", "<!-- Follow-up work or constraints implied. -->"),
            ],
            preamble="<!-- Auto-derived from in-code rationale comments during onboarding. "
            "Review, refine, and accept (or delete) before treating as authoritative. -->",
        )
        (proposals_dir / filename).write_text(body, encoding="utf-8")
        created.append((proposals_dir / filename).relative_to(root).as_posix())

    return {
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "next_action": (
            "Review the proposed rationale records and accept, refine, or delete them."
            if created
            else "No new proposable rationale comments found."
        ),
    }


def stale_sources(root: Path, config: dict, store: GraphStore) -> list[str]:
    """Return indexed source paths whose on-disk content no longer matches the
    hash in the index, plus paths deleted since indexing. Used to warn callers
    that retrieval may reflect an out-of-date graph."""
    root = root.resolve()
    indexed = store.all_source_hashes()
    stale: list[str] = []
    for rel, indexed_hash in indexed.items():
        # Derived pseudo-sources (@project-relations, @communities) and bootstrap
        # artifacts are not files on disk; skip them.
        if rel.startswith("@"):
            continue
        path = root / rel
        if not path.is_file():
            stale.append(rel)
            continue
        try:
            if compute_source_hash(path) != indexed_hash:
                stale.append(rel)
        except OSError:
            stale.append(rel)
    return sorted(stale)


def _filesystem_changed_paths(root: Path, config: dict) -> tuple[list[str], list[str]]:
    """Detect changed and new source paths without Git by comparing on-disk
    hashes against the last indexed hash stored in the graph."""
    discovered, _ = discover_code_paths(root, config)
    changed: list[str] = []
    warnings: list[str] = []
    store_path = _index_path(root, config)
    if not store_path.exists():
        warnings.append("No index exists; run whyloom index so filesystem change detection has a baseline.")
        return sorted(path.relative_to(root).as_posix() for path in discovered), warnings
    with GraphStore(store_path, create=False) as store:
        for path in discovered:
            rel = path.relative_to(root).as_posix()
            try:
                current = compute_source_hash(path)
            except OSError:
                continue
            if store.source_hash(rel) != current:
                changed.append(rel)
    return sorted(changed), warnings


def _changed_symbols(root: Path, config: dict, paths: list[str]) -> dict[str, list[str]]:
    """Return the indexed symbols per changed source file so an agent brief can
    show what structurally changed, not just which files were touched."""
    source_paths = [p for p in paths if p.endswith(".py")]
    if not source_paths:
        return {}
    store_path = _index_path(root, config)
    if not store_path.exists():
        return {}
    brief: dict[str, list[str]] = {}
    with GraphStore(store_path, create=False) as store:
        for rel in source_paths:
            rows = store.connection.execute(
                "SELECT label FROM nodes WHERE source_path = ? AND type = 'Symbol' ORDER BY label",
                (rel,),
            ).fetchall()
            symbols = [row["label"] for row in rows]
            if symbols:
                brief[rel] = symbols
    return brief

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
    database = _index_path(root, config)
    outdated_sources = 0
    integrity_ok = True
    stale: list[str] = []
    if database.is_file():
        try:
            with GraphStore(database, create=False) as store:
                integrity_ok = store.integrity_ok()
                if integrity_ok:
                    outdated_sources = store.outdated_source_count(INDEX_FORMAT_VERSION)
                    stale = stale_sources(root, config, store)
        except CorruptIndexError:
            integrity_ok = False
    # Validation opens the store too; a corrupt index makes it non-ready, not a crash.
    try:
        validation = validate_project(root, config)
    except CorruptIndexError:
        validation = {"valid": False, "records": 0, "errors": [{"code": "IDX003", "message": "index is corrupt"}], "warnings": []}
        integrity_ok = False
    checks = [
        {"name": "repository", "ok": root.is_dir(), "detail": str(root)},
        {"name": "configuration", "ok": (root / "whyloom.yaml").is_file(), "detail": "whyloom.yaml"},
        {"name": "records", "ok": (root / config["records_dir"]).is_dir(), "detail": config["records_dir"]},
        {
            "name": "integrity",
            "ok": not database.is_file() or integrity_ok,
            "detail": "ok" if integrity_ok else "index is corrupt; delete the cache and reindex",
        },
        {
            "name": "index",
            "ok": database.is_file() and integrity_ok and outdated_sources == 0,
            "detail": config["database"] if outdated_sources == 0 else f"{outdated_sources} sources require reindexing",
        },
        {
            "name": "freshness",
            "ok": not stale,
            "detail": "index matches working tree" if not stale else f"{len(stale)} source(s) changed since indexing",
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


def _git_changed_paths(root: Path) -> tuple[list[str], str, list[str]]:
    """Return changed paths from Git, the baseline used, and any warnings.
    Falls through to an empty result (never raises) when Git is unavailable so
    callers can degrade to filesystem change detection."""
    warnings: list[str] = []
    try:
        inside_repo = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip() == "true"
    except OSError:
        return [], "unavailable", warnings
    if not inside_repo:
        # No repository at all: let filesystem change detection own this run.
        return [], "unavailable", warnings
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
    diff_text = subprocess.run(diff_command, cwd=root, check=False, capture_output=True, text=True).stdout
    status_text = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all", "-z"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    ).stdout
    changed: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            changed.append(line.removeprefix("+++ b/"))
    for entry in status_text.split("\0"):
        if len(entry) >= 4:
            changed.append(entry[3:])
    return changed, baseline, warnings


def reflect_project(
    root: Path,
    task_summary: str,
    diff_text: str | None = None,
    config: dict | None = None,
) -> dict:
    root = root.resolve()
    config = config or dict(DEFAULT_CONFIG)
    records_dir = config["records_dir"]
    warnings: list[str] = []

    if diff_text is not None:
        baseline = "provided_diff"
        changed_paths = [
            line.removeprefix("+++ b/") for line in diff_text.splitlines() if line.startswith("+++ b/")
        ]
    else:
        changed_paths, baseline, warnings = _git_changed_paths(root)
        if not changed_paths:
            # Git is absent or found nothing: detect changes from indexed hashes
            # so reflect works on any folder, no version control required.
            fs_changed, fs_warnings = _filesystem_changed_paths(root, config)
            if fs_changed:
                changed_paths = fs_changed
                if baseline == "unavailable":
                    baseline = "filesystem"
            warnings.extend(fs_warnings)

    # Drop Whyloom's own scaffolding so targets name what the work actually changed.
    changed_paths = sorted(
        {p for p in changed_paths if not any(p == n or p.startswith(n) for n in _REFLECT_TARGET_NOISE)}
    )
    symbol_brief = _changed_symbols(root, config, changed_paths)

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
        "targets": changed_paths,
        "constraints": [],
        "supersedes": [],
    }

    evidence_lines = []
    for item in changed_paths:
        symbols = symbol_brief.get(item)
        if symbols:
            evidence_lines.append(f"- `{item}` — symbols: {', '.join(symbols)}")
        else:
            evidence_lines.append(f"- `{item}`")

    body = _render_record_markdown(
        metadata,
        [
            ("Context", task_summary.strip()),
            ("Decision", "<!-- agent: the concrete choice this work embodies. -->"),
            ("Rationale", "<!-- agent: why this choice, grounded in the changed symbols and evidence below. -->"),
            ("Alternatives", "<!-- agent: options considered and why they were not chosen; omit if unknown. -->"),
            ("Consequences", "<!-- agent: follow-up work, costs, and constraints this introduces. -->"),
            ("Open questions", "<!-- agent: anything you could not determine from the evidence. -->"),
            ("Evidence", "\n".join(evidence_lines) or "- No changed paths were detected."),
        ],
        preamble="<!-- agent: complete every section below from the task summary, the changed files, and their symbols. "
        "Cite evidence paths. State confidence. Record uncertainty as open questions. Do not invent rationale. -->",
    )
    path.write_text(body, encoding="utf-8")
    return {
        "proposal": path.relative_to(root).as_posix(),
        "status": "proposed",
        "changed_paths": changed_paths,
        "agent_brief": {
            "task_summary": task_summary.strip(),
            "changed_symbols": symbol_brief,
            "sections_to_complete": ["Decision", "Rationale", "Alternatives", "Consequences", "Open questions"],
            "instruction": (
                "Fill each marked section from the task summary, changed files, and symbols. "
                "This proposal stays status: proposed until a human accepts it in review."
            ),
        },
        "requires_review": True,
        "baseline": baseline,
        "warnings": warnings,
    }


def format_human(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)
