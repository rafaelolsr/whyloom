from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, date, datetime
from pathlib import Path

import yaml

from .codegraph import source_hash as compute_source_hash
from .config import DEFAULT_CONFIG, resolve_repository_path
from .indexer import discover_code_paths, index_project
from .migrations import INDEX_FORMAT_VERSION
from .models import Diagnostic, RecordStatus
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


def _evidence_path(source: str) -> str | None:
    """A repo-relative file path if the evidence source names one, else None.

    Evidence sources are free text (a file, a URL, a doc title, a commit). Only
    file-like sources can be verified against the working tree; strip an optional
    `:line` suffix and treat obvious non-paths (URLs) as unverifiable-here."""
    source = (source or "").strip()
    if not source or "://" in source:
        return None
    candidate = source.split(":", 1)[0].strip() if source.rsplit(":", 1)[-1].isdigit() else source
    # Must look like a repo path, not prose (no spaces, has a suffix or a slash).
    if " " in candidate or ("/" not in candidate and "." not in candidate):
        return None
    return candidate.lstrip("./")


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
                "status": "draft",
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

    # Conflict check on what was just drafted: a new proposal that shares a
    # target with an authoritative record is a supersession candidate the
    # reviewer should resolve — surface it now, not at some later validate.
    conflicts: list[dict] = []
    if created:
        all_records, _ = discover_records(root, config["records_dir"])
        created_paths = set(created)
        conflicts = [
            item.model_dump(mode="json")
            for item in _conflict_diagnostics(all_records)
            if item.path in created_paths
        ]

    if created:
        next_action = "Review the proposed rationale records and accept, refine, or delete them."
    elif skipped:
        next_action = (
            f"No new proposals: {skipped} proposable comment(s) were already proposed. "
            "Review the existing proposals under .whyloom/proposals/."
        )
    else:
        next_action = "No WHY/DECISION/HACK rationale comments were found to propose."
    return {
        "created": created,
        "created_count": len(created),
        "skipped": skipped,
        "conflicts": conflicts,
        "next_action": next_action,
    }


_STATUS_LINE = re.compile(r"^(status:\s*)(\S+)", re.MULTILINE)
_ID_LINE = re.compile(r"^id:\s*(\S+)", re.MULTILINE)
# A machine-confidence line marks a record as still-unreviewed draft. Human
# acceptance supersedes the machine's self-assessment, so acceptance removes it.
_CONFIDENCE_LINE = re.compile(r"^confidence:.*\n", re.MULTILINE)


def _human_verifier() -> str:
    """The OKF actor id for the current human reviewer (`human:<os-user>`)."""
    import getpass

    try:
        user = getpass.getuser()
    except Exception:  # pragma: no cover - environments without a resolvable user
        user = "unknown"
    return f"human:{user}"


def _append_verified_block(text: str, verifier: str, at: str) -> str:
    """Append a `verified` frontmatter entry inside the YAML block, before its
    closing `---`. If a `verified:` key already exists it appends a list item;
    otherwise it inserts a new `verified:` list. Deterministic, order-preserving."""
    lines = text.splitlines(keepends=True)
    # Find the closing '---' of the frontmatter (second '---' line).
    fences = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if len(fences) < 2:
        return text
    close = fences[1]
    # Quote the timestamp so YAML keeps it a string (an unquoted ISO datetime is
    # parsed as a native datetime, which the string-typed model field rejects).
    entry = [f"  - by: {verifier}\n", f'    at: "{at}"\n']
    for i in range(fences[0] + 1, close):
        if lines[i].startswith("verified:"):
            # Insert list items right after the existing key.
            insert_at = i + 1
            while insert_at < close and lines[insert_at].startswith(("  -", "    ")):
                insert_at += 1
            lines[insert_at:insert_at] = entry
            return "".join(lines)
    lines[close:close] = ["verified:\n", *entry]
    return "".join(lines)


def accept_records(
    root: Path,
    config: dict,
    *,
    ids: list[str] | None = None,
    all_proposed: bool = False,
    verifier: str | None = None,
    at: str | None = None,
) -> dict:
    """Flip proposed records to accepted — the sanctioned way a human confirms
    review from the CLI. Only ``status`` changes; the record file is otherwise
    preserved. Bulk by default (``all_proposed``) so accepting many records is one
    reviewed action, never a per-record chore.

    This is optional: editing the record's status in a pull request is the
    primary, zero-setup human-review gate. Records are files; the PR review is
    where acceptance naturally happens."""
    root = root.resolve()
    records_dir = root / config["records_dir"]
    wanted = {i.upper() for i in (ids or [])}
    accepted: list[str] = []
    skipped: list[dict] = []

    for path in sorted(records_dir.rglob("*.md")):
        # Skip the non-record scaffolding (overview, glossary, templates, cache).
        if any(part in {"templates", "cache"} for part in path.relative_to(records_dir).parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        id_match = _ID_LINE.search(text)
        status_match = _STATUS_LINE.search(text)
        if not id_match or not status_match:
            continue
        record_id = id_match.group(1)
        current_status = status_match.group(2)

        selected = all_proposed or record_id.upper() in wanted
        if not selected:
            continue
        # This id was matched to a file — never report it "not found" later.
        wanted.discard(record_id.upper())
        if current_status in {"stable", "accepted", "implemented"}:
            skipped.append({"id": record_id, "reason": "already accepted"})
            continue
        if current_status not in {"draft", "proposed"}:
            skipped.append({"id": record_id, "reason": f"status is '{current_status}', not draft"})
            continue
        # Acceptance is a human verification event: flip the lifecycle to the OKF
        # authoritative value (stable) and record WHO verified and WHEN. The human
        # verified[] entry — not the status alone — is the review gate TRUST001
        # checks. Drop the machine confidence: the human's judgment supersedes it.
        updated = _STATUS_LINE.sub(r"\1stable", text, count=1)
        updated = _CONFIDENCE_LINE.sub("", updated, count=1)
        updated = _append_verified_block(updated, verifier or _human_verifier(), at or datetime.now(UTC).isoformat())
        path.write_text(updated, encoding="utf-8")
        accepted.append(record_id)

    for missing in sorted(wanted):
        skipped.append({"id": missing, "reason": "not found"})

    reindex = index_project(root, config) if accepted else None
    return {
        "accepted": accepted,
        "accepted_count": len(accepted),
        "skipped": skipped,
        "reindexed": bool(reindex),
        "next_action": (
            f"Accepted {len(accepted)} record(s). Commit the change so the acceptance is reviewed in Git."
            if accepted
            else "No records accepted."
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
status: draft
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
status: draft
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


def _supersession_linked(first: str, second: str, supersedes: dict[str, list[str]]) -> bool:
    """Whether a supersession chain (transitive, either direction) connects two
    record ids. Linked records are one lineage, not a conflict."""

    def reaches(start: str, goal: str) -> bool:
        seen: set[str] = set()
        frontier = [start]
        while frontier:
            current = frontier.pop()
            if current == goal:
                return True
            if current in seen:
                continue
            seen.add(current)
            frontier.extend(supersedes.get(current, []))
        return False

    return reaches(first, second) or reaches(second, first)


# Two records conflict only when they claim substantially the same SCOPE, not
# when they merely touch one shared file — complementary decisions legitimately
# co-govern a path (dogfooding: whyloom's own decisions overlap on languages.py
# without contradicting each other). Jaccard over target sets captures "same
# subject": identical single-target records score 1.0; a broad record brushing a
# focused one scores low and stays silent.
_CONFLICT_SCOPE_OVERLAP = 0.5


def _conflict_diagnostics(records: list) -> list[Diagnostic]:
    """Detect same-type records claiming substantially the same targets.

    Two authoritative records of one type governing the same scope hand an
    agent two sources of truth (CONFLICT002) unless a supersession chain links
    them. A draft covering the scope of an authoritative same-type record is a
    supersession candidate the reviewer should link, refine, or discard before
    accepting (CONFLICT003). Advisory by design: warnings, never errors — the
    human resolves the conflict at review, the check only surfaces it."""
    diagnostics: list[Diagnostic] = []
    supersedes = {record.id: record.supersedes for record in records}
    candidates = [
        record
        for record in records
        # Only the "why" record types can contradict each other; architecture and
        # glossary records legitimately overlap decisions on the same paths.
        if record.type.value in {"decision", "constraint"} and record.targets
    ]

    def scope_overlap(first, second) -> tuple[float, list[str]]:
        a, b = set(first.targets), set(second.targets)
        shared = a & b
        if not shared:
            return 0.0, []
        return len(shared) / len(a | b), sorted(shared)

    for i, first in enumerate(candidates):
        for second in candidates[i + 1 :]:
            if first.type != second.type or first.id == second.id:
                continue
            statuses = {first.okf_status(), second.okf_status()}
            if statuses == {RecordStatus.STABLE}:
                code = "CONFLICT002"
            elif statuses == {RecordStatus.STABLE, RecordStatus.DRAFT}:
                code = "CONFLICT003"
            else:
                continue  # deprecated or draft-draft pairs are history, not conflict
            overlap, shared = scope_overlap(first, second)
            if overlap < _CONFLICT_SCOPE_OVERLAP:
                continue
            if _supersession_linked(first.id, second.id, supersedes):
                continue
            sample = ", ".join(shared[:3]) + ("…" if len(shared) > 3 else "")
            if code == "CONFLICT002":
                message = (
                    f"{first.id} and {second.id} both govern the same scope ({sample}) as {first.type.value}s; "
                    "if one replaces the other, link them with supersedes"
                )
                path = second.path.as_posix()
            else:
                draft, authoritative = (first, second) if first.okf_status() == RecordStatus.DRAFT else (second, first)
                message = (
                    f"draft {draft.id} covers the scope of authoritative {authoritative.id} ({sample}); "
                    "review whether it supersedes, refines, or duplicates it before accepting"
                )
                path = draft.path.as_posix()
            diagnostics.append(Diagnostic(code=code, severity="warning", message=message, path=path))
    return diagnostics


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
        # Trust gate: a governing record must be verified. A DECISION or CONSTRAINT
        # states WHY a choice was made — not provable from code — so it requires a
        # HUMAN verifier. A structural/role (architecture) record states what the
        # code IS, which is provable from evidence, so a grounded one may be
        # verified by a process (e.g. process:bootstrap) and govern human-less
        # (DEC-0008). Either way an unverified authoritative record is invalid.
        if record.okf_status() in {RecordStatus.STABLE}:
            if record.is_structural():
                ok = record.is_verified()  # human or process (grounding checked by TRUST002)
                hint = "verify it (a grounded structural record may be verified by process:bootstrap)"
            else:
                ok = record.human_verified()
                hint = "a decision/constraint states WHY and requires a human verified[] entry (whyloom accept)"
            if not ok:
                diagnostics.append(
                    Diagnostic(
                        code="TRUST001",
                        severity="error",
                        message=f"authoritative record (status '{record.status.value}') is unverified; {hint}",
                        path=record.path.as_posix(),
                    )
                )
        # Evidence-grounding gate (DEC-0008): a governing record's claims must be
        # anchored in real code. Trust is consistency with the codebase, not a
        # signature — so an authoritative record that cites no resolvable file
        # (no targets, and no evidence source naming an existing file) is
        # ungrounded and cannot govern. Catches hallucinated rationale, whose
        # "why" cites nothing that resolves.
        if record.okf_status() in {RecordStatus.STABLE}:
            grounded_targets = bool(record.targets)
            grounded_evidence = any(
                (root / _evidence_path(item.source)).exists()
                for item in record.evidence
                if _evidence_path(item.source)
            )
            if not grounded_targets and not grounded_evidence:
                diagnostics.append(
                    Diagnostic(
                        code="TRUST002",
                        severity="error",
                        message=(
                            "authoritative record cites no verifiable code: add a `targets` path or an "
                            "`evidence` entry naming a real file. Ungrounded rationale cannot govern "
                            "(trust is consistency with the code, not authorship)."
                        ),
                        path=record.path.as_posix(),
                    )
                )

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
    diagnostics.extend(_conflict_diagnostics(records))

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


def _precedents(
    root: Path,
    config: dict,
    task_summary: str,
    changed_paths: list[str],
    *,
    limit: int = 3,
) -> list[dict]:
    """Rank previously reviewed decisions relevant to the work being reflected,
    so an agent links or supersedes an existing decision instead of duplicating
    it. Deterministic: target overlap with the changed paths plus title-token
    overlap with the task summary — no LLM, no index required.

    Deprecated (superseded/rejected) decisions are included on purpose: "we
    tried this and reversed it" is the highest-value precedent."""
    records, _ = discover_records(root, config["records_dir"])
    summary_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", task_summary.casefold())}
    changed = set(changed_paths)
    scored: list[tuple[float, str, dict]] = []
    for record in records:
        # Drafts are not precedent — they were never reviewed.
        if record.type.value != "decision" or record.okf_status() == RecordStatus.DRAFT:
            continue
        overlapping: list[str] = []
        score = 0.0
        for target in record.targets:
            if target in changed:
                overlapping.append(target)
                score += 2.0
            elif any(p.startswith(target.rstrip("/") + "/") or target.startswith(p.rstrip("/") + "/") for p in changed):
                overlapping.append(target)
                score += 1.0
        title_tokens = {token for token in re.findall(r"[a-z0-9]{3,}", record.title.casefold())}
        score += len(summary_tokens & title_tokens)
        if score <= 0:
            continue
        scored.append(
            (
                score,
                record.id,
                {
                    "id": record.id,
                    "title": record.title,
                    "status": record.status.value,
                    "reversed": record.okf_status() == RecordStatus.DEPRECATED,
                    "path": record.path.as_posix(),
                    "overlapping_targets": sorted(set(overlapping)),
                    "score": score,
                },
            )
        )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in scored[:limit]]


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
    # Precedent check before drafting: has a reviewed decision already covered
    # this ground? Surfacing it here steers the author toward linking (via
    # supersedes/constraints) instead of writing a duplicate the reviewer must
    # then reconcile.
    precedents = _precedents(root, config, task_summary, changed_paths)

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
    proposal_id = f"PROP-{stamp}"
    path = root / records_dir / "proposals" / f"{proposal_id.lower()}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "id": proposal_id,
        "type": "decision",
        "title": f"Review learning from: {task_summary[:72]}",
        "status": "draft",
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
            ("Decision", "<!-- agent: the concrete choice this work embodies. Cite the changed file/symbol that carries it, e.g. `src/auth.py:rotate`. -->"),
            ("Rationale", "<!-- agent: why this choice. Every sentence must be traceable to a changed symbol in the Evidence list. If you cannot point at the code for a claim, it does not belong here — move it to Open questions. -->"),
            ("Alternatives", "<!-- agent: options considered and why not chosen, only if the diff or task summary shows them; else omit. -->"),
            ("Consequences", "<!-- agent: follow-up work, costs, and constraints this introduces, grounded in the change. -->"),
            ("Open questions", "<!-- agent: everything you could NOT ground in the evidence — the intent behind the change, tradeoffs not visible in the diff, anything you are inferring. Put it here rather than asserting it as rationale. -->"),
            ("Evidence", "\n".join(evidence_lines) or "- No changed paths were detected."),
        ],
        preamble="<!-- agent: trust here is grounding, not authorship (see DEC-0008). Complete each section ONLY from the "
        "task summary and the changed files/symbols in Evidence. Cite the evidence path for every claim. Anything you "
        "cannot tie to the code — intent, tradeoffs, alternatives not in the diff — goes in Open questions, never asserted "
        "as rationale. An ungrounded record fails validation (TRUST002) and cannot govern. Do not invent rationale. -->",
    )
    path.write_text(body, encoding="utf-8")
    return {
        "proposal": path.relative_to(root).as_posix(),
        "status": "draft",
        "changed_paths": changed_paths,
        "precedents": precedents,
        "agent_brief": {
            "task_summary": task_summary.strip(),
            "changed_symbols": symbol_brief,
            "sections_to_complete": ["Decision", "Rationale", "Alternatives", "Consequences", "Open questions"],
            "instruction": (
                "Fill each marked section from the task summary, changed files, and symbols. "
                "This proposal stays status: draft until a human verifies it in review."
                + (
                    " Related reviewed decisions exist (see precedents): reference them via constraints, "
                    "or supersedes if this work replaces one — do not restate them."
                    if precedents
                    else ""
                )
            ),
        },
        "requires_review": True,
        "baseline": baseline,
        "warnings": warnings,
    }


def format_human(payload: dict) -> str:
    return json.dumps(payload, indent=2, default=str)
