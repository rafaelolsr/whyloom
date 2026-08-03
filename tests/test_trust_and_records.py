"""Pilot findings: Architecture/Incident records must surface in retrieval, and
agent-authored accepted records must be flagged (warn, don't block)."""

import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import _looks_inferred, context_packet, explain_target
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_architecture_record_surfaces_in_explain(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / ".whyloom" / "architecture").mkdir(parents=True, exist_ok=True)
    (root / ".whyloom" / "architecture" / "0001-shell.md").write_text(
        "---\nid: ARC-0001\ntype: architecture\ntitle: Deterministic shell\nstatus: accepted\n"
        "date: 2026-08-03\ntargets:\n- src/sample/auth.py\nconstraints: []\nsupersedes: []\n---\n\n"
        "## Observation\nx\n## Inference\nx\n## Consequences\nx\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = explain_target(store, "src/sample/auth.py")
    assert any(r["id"] == "ARC-0001" for r in result["governing_records"])


def test_governing_record_surfaces_when_seed_is_a_symbol(tmp_path):
    # Pilot bug: lexical search matches a Symbol inside a file, but the governing
    # record links to the File node. Without promoting the symbol's file to a
    # seed, the record sits past max_depth and never surfaces. Query a symbol
    # name (not the record's title) to exercise the Symbol->File->Record climb.
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / ".whyloom" / "architecture").mkdir(parents=True, exist_ok=True)
    (root / ".whyloom" / "architecture" / "0001-shell.md").write_text(
        "---\nid: ARC-0001\ntype: architecture\ntitle: Deterministic shell\nstatus: accepted\n"
        "date: 2026-08-03\ntargets:\n- src/sample/auth.py\nconstraints: []\nsupersedes: []\n---\n\n"
        "## Observation\nx\n## Inference\nx\n## Consequences\nx\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        packet = context_packet(store, "fingerprint")
    assert any(r["id"] == "ARC-0001" for r in packet["governing_records"])


def test_looks_inferred_heuristic():
    assert _looks_inferred({"id": "ARC-INFERRED-001", "data": {}})
    assert _looks_inferred({"id": "DEC-0001", "data": {"confidence": "high"}})
    assert not _looks_inferred({"id": "DEC-0001", "data": {"confidence": None}})
    assert not _looks_inferred({"id": "CON-0001", "data": {}})


def test_agent_authored_accepted_record_is_flagged(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / ".whyloom" / "architecture").mkdir(parents=True, exist_ok=True)
    # An accepted record with a confidence score — looks agent-authored.
    (root / ".whyloom" / "architecture" / "0001-inferred.md").write_text(
        "---\nid: ARC-INFERRED-001\ntype: architecture\ntitle: Token storage shell\nstatus: accepted\n"
        "date: 2026-08-03\ntargets:\n- src/sample/auth.py\nconstraints: []\nsupersedes: []\nconfidence: high\n---\n\n"
        "## Observation\nx\n## Inference\nx\n## Consequences\nx\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        packet = context_packet(store, "token storage")
    # Surfaced (not blocked)...
    assert any(r["id"] == "ARC-INFERRED-001" for r in packet["governing_records"])
    # ...but flagged for provenance confirmation.
    assert any("agent-authored" in w for w in packet["warnings"])
