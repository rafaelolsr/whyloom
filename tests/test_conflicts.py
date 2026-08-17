"""Conflict detection: same-type records claiming the same target are surfaced
as advisory warnings (never errors) so the human resolves them at review."""

import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.operations import validate_project

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _write_record(root, relative, *, record_id, record_type, title, status, targets, supersedes=(), verified=True):
    verified_block = '\nverified:\n  - by: human:maintainer\n    at: "2026-07-31T00:00:00Z"' if verified else ""
    targets_block = "\n".join(f"  - {t}" for t in targets)
    supersedes_value = "[" + ", ".join(supersedes) + "]"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""---
id: {record_id}
type: {record_type}
title: {title}
status: {status}
date: 2026-08-01
targets:
{targets_block}
constraints: []
supersedes: {supersedes_value}{verified_block}
---

## Decision

Body for {record_id}.

## Rationale

Grounded in the target file.
""",
        encoding="utf-8",
    )


def _conflict_warnings(result, code):
    return [w for w in result["warnings"] if w["code"] == code]


def test_two_governing_decisions_on_same_target_conflict(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    # Fixture already has governing DEC-0001 targeting src/sample/auth.py.
    _write_record(
        root,
        ".whyloom/decisions/0002-competing.md",
        record_id="DEC-0002",
        record_type="decision",
        title="Competing take on token storage",
        status="stable",
        targets=["src/sample/auth.py"],
    )
    result = validate_project(root, DEFAULT_CONFIG)
    assert result["valid"]  # advisory: warnings never fail validation
    conflicts = _conflict_warnings(result, "CONFLICT002")
    assert len(conflicts) == 1
    assert "DEC-0001" in conflicts[0]["message"] and "DEC-0002" in conflicts[0]["message"]


def test_supersession_chain_resolves_conflict(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    _write_record(
        root,
        ".whyloom/decisions/0002-replacement.md",
        record_id="DEC-0002",
        record_type="decision",
        title="Replacement for token storage decision",
        status="stable",
        targets=["src/sample/auth.py"],
        supersedes=["DEC-0001"],
    )
    result = validate_project(root, DEFAULT_CONFIG)
    assert not _conflict_warnings(result, "CONFLICT002")


def test_transitive_supersession_resolves_conflict(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    _write_record(
        root,
        ".whyloom/decisions/0002-middle.md",
        record_id="DEC-0002",
        record_type="decision",
        title="Middle of the lineage",
        status="deprecated",
        targets=["src/sample/auth.py"],
        supersedes=["DEC-0001"],
    )
    _write_record(
        root,
        ".whyloom/decisions/0003-latest.md",
        record_id="DEC-0003",
        record_type="decision",
        title="Latest in the lineage",
        status="stable",
        targets=["src/sample/auth.py"],
        supersedes=["DEC-0002"],
    )
    result = validate_project(root, DEFAULT_CONFIG)
    # DEC-0003 supersedes DEC-0001 transitively through DEC-0002: one lineage.
    assert not _conflict_warnings(result, "CONFLICT002")


def test_partial_scope_overlap_stays_silent(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / "src" / "sample" / "session.py").write_text("def touch():\n    return 1\n", encoding="utf-8")
    (root / "src" / "sample" / "audit.py").write_text("def log():\n    return 1\n", encoding="utf-8")
    # Shares one target with DEC-0001 but claims a broader, different scope
    # (Jaccard 1/3): complementary decisions co-governing a file, not a conflict.
    _write_record(
        root,
        ".whyloom/decisions/0002-broad.md",
        record_id="DEC-0002",
        record_type="decision",
        title="Session and audit handling",
        status="stable",
        targets=["src/sample/auth.py", "src/sample/session.py", "src/sample/audit.py"],
    )
    result = validate_project(root, DEFAULT_CONFIG)
    assert not _conflict_warnings(result, "CONFLICT002")


def test_different_types_on_same_target_do_not_conflict(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    # Fixture ships DEC-0001 (decision) and CON-0001 (constraint) on the same
    # target — a decision and a constraint legitimately co-govern one path.
    result = validate_project(root, DEFAULT_CONFIG)
    assert not _conflict_warnings(result, "CONFLICT002")
    assert not _conflict_warnings(result, "CONFLICT003")


def test_draft_sharing_target_with_governing_record_flags_supersession_candidate(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    _write_record(
        root,
        ".whyloom/proposals/prop-new-take.md",
        record_id="PROP-NEW-TAKE",
        record_type="decision",
        title="New take on token storage",
        status="draft",
        targets=["src/sample/auth.py"],
        verified=False,
    )
    result = validate_project(root, DEFAULT_CONFIG)
    assert result["valid"]
    candidates = _conflict_warnings(result, "CONFLICT003")
    assert len(candidates) == 1
    assert "PROP-NEW-TAKE" in candidates[0]["message"] and "DEC-0001" in candidates[0]["message"]


def test_propose_surfaces_conflicts_for_created_proposals(tmp_path):
    from whyloom.indexer import index_project
    from whyloom.operations import propose_from_rationale

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    auth = root / "src" / "sample" / "auth.py"
    auth.write_text(
        auth.read_text(encoding="utf-8") + "\n# DECISION: fingerprints only, never raw tokens\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    result = propose_from_rationale(root, DEFAULT_CONFIG)
    assert result["created"]
    # The new draft targets src/sample/auth.py, already governed by DEC-0001.
    assert any(c["code"] == "CONFLICT003" for c in result["conflicts"])
