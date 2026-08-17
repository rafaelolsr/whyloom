"""Precedent surfacing in reflect: previously reviewed decisions relevant to the
work are ranked and offered before a new draft duplicates them."""

import shutil
from pathlib import Path

from whyloom.operations import reflect_project

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"

AUTH_DIFF = "diff --git a/src/sample/auth.py b/src/sample/auth.py\n+++ b/src/sample/auth.py\n"


def _add_decision(root, name, *, record_id, title, status, targets, supersedes="[]"):
    (root / ".whyloom" / "decisions" / name).write_text(
        f"""---
id: {record_id}
type: decision
title: {title}
status: {status}
date: 2026-08-01
targets:
{chr(10).join(f"  - {t}" for t in targets)}
constraints: []
supersedes: {supersedes}
verified:
  - by: human:maintainer
    at: "2026-08-01T00:00:00Z"
---

## Decision

Body for {record_id}.
""",
        encoding="utf-8",
    )


def test_reflect_surfaces_target_overlap_precedent(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    result = reflect_project(root, "Rotate token fingerprints on login", AUTH_DIFF)
    precedents = result["precedents"]
    assert [r["id"] for r in precedents] == ["DEC-0001"]
    assert precedents[0]["overlapping_targets"] == ["src/sample/auth.py"]
    assert precedents[0]["reversed"] is False
    assert "precedents" in result["agent_brief"]["instruction"]


def test_reflect_includes_superseded_decisions_as_reversed(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    _add_decision(
        root,
        "0002-old-take.md",
        record_id="DEC-0002",
        title="Store tokens in browser storage",
        status="superseded",
        targets=["src/sample/auth.py"],
    )
    result = reflect_project(root, "Change how tokens are stored in the browser", AUTH_DIFF)
    by_id = {r["id"]: r for r in result["precedents"]}
    assert "DEC-0002" in by_id
    assert by_id["DEC-0002"]["reversed"] is True


def test_reflect_ranks_by_overlap_and_title_match(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    _add_decision(
        root,
        "0003-unrelated.md",
        record_id="DEC-0003",
        title="Choose SQLite for the cache",
        status="stable",
        targets=["src/sample/auth.py"],
    )
    result = reflect_project(root, "Keep tokens out of browser storage entirely", AUTH_DIFF)
    ids = [r["id"] for r in result["precedents"]]
    # DEC-0001 shares the target AND the task words; DEC-0003 only the target.
    assert ids[0] == "DEC-0001"
    assert "DEC-0003" in ids


def test_reflect_limits_precedents_to_three(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    for i in range(2, 7):
        _add_decision(
            root,
            f"000{i}-extra.md",
            record_id=f"DEC-000{i}",
            title=f"Auth decision number {i}",
            status="stable",
            targets=["src/sample/auth.py"],
        )
    result = reflect_project(root, "Adjust auth flow", AUTH_DIFF)
    assert len(result["precedents"]) == 3


def test_reflect_without_related_records_has_no_precedents(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    diff = "diff --git a/docs/notes.md b/docs/notes.md\n+++ b/docs/notes.md\n"
    result = reflect_project(root, "completely unrelated frobnication work", diff)
    assert result["precedents"] == []
    assert "precedents" not in result["agent_brief"]["instruction"]


def test_drafts_are_not_precedent(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / ".whyloom" / "proposals").mkdir(exist_ok=True)
    (root / ".whyloom" / "proposals" / "prop-draft.md").write_text(
        """---
id: PROP-DRAFT
type: decision
title: Unreviewed idea about auth
status: draft
date: 2026-08-01
targets:
  - src/sample/auth.py
constraints: []
supersedes: []
---

## Decision

Not yet reviewed.
""",
        encoding="utf-8",
    )
    result = reflect_project(root, "Adjust auth flow", AUTH_DIFF)
    assert "PROP-DRAFT" not in [r["id"] for r in result["precedents"]]
