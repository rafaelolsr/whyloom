"""Resolution trust: path-like targets never fuzzy-resolve to unrelated nodes,
directory record targets are explainable, and impact counts module importers.

These reproduce three bugs a real-repo beta evaluation found — each test fails
without its fix (verified during development)."""

import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import explain_target, impact_analysis
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _repo(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    return root


def _store(root):
    return GraphStore(root / DEFAULT_CONFIG["database"], create=False)


def test_explain_nonexistent_pathlike_target_is_not_found(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    with _store(root) as store:
        result = explain_target(store, "doesnotexist.py", root=root, config=DEFAULT_CONFIG)
    # Trust rule: a path that names no indexed file must NOT confidently attach
    # the lexically-nearest record.
    assert result["found"] is False
    assert result.get("governing_records", []) == []


def test_explain_basename_still_resolves_by_suffix(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    with _store(root) as store:
        result = explain_target(store, "auth.py", root=root, config=DEFAULT_CONFIG)
    assert result["found"] is True
    assert result["node"]["path"] == "src/sample/auth.py"


def test_explain_directory_target_finds_governing_records(tmp_path):
    root = _repo(tmp_path)
    # Point the fixture decision at the directory instead of the file.
    decision = root / ".whyloom" / "decisions" / "0001-token-storage.md"
    decision.write_text(
        decision.read_text(encoding="utf-8").replace("src/sample/auth.py", "src/sample"), encoding="utf-8"
    )
    constraint = root / ".whyloom" / "constraints" / "0001-no-token-storage.md"
    constraint.write_text(
        constraint.read_text(encoding="utf-8").replace("src/sample/auth.py", "src/sample"), encoding="utf-8"
    )
    index_project(root, DEFAULT_CONFIG)
    with _store(root) as store:
        result = explain_target(store, "src/sample", root=root, config=DEFAULT_CONFIG)
    assert result["found"] is True
    assert result["node"]["type"] == "Directory"
    assert any(r["id"] == "DEC-0001" for r in result["governing_records"])
    # Trailing slash resolves the same way.
    with _store(root) as store:
        slashed = explain_target(store, "src/sample/", root=root, config=DEFAULT_CONFIG)
    assert slashed["found"] is True


def test_impact_counts_module_importers_as_dependents(tmp_path):
    root = _repo(tmp_path)
    # A production module that imports auth at module level but calls nothing.
    (root / "src" / "sample" / "service.py").write_text(
        "from src.sample.auth import fingerprint\n\nHANDLERS = [fingerprint]\n", encoding="utf-8"
    )
    index_project(root, DEFAULT_CONFIG)
    with _store(root) as store:
        result = impact_analysis(store, "src/sample/auth.py")
    callers = result["affected"]["downstream_callers"]
    # The importing FILE must appear as a dependent, not only symbol callers.
    assert any(c["path"] == "src/sample/service.py" and c["via"] == "IMPORTS" for c in callers)


def test_fuzzy_symbol_resolution_carries_warning(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    with _store(root) as store:
        # Name-like query with no exact symbol: fuzzy is allowed but labeled.
        result = explain_target(store, "fingerprinting", root=root, config=DEFAULT_CONFIG)
    if result["found"]:
        assert any("closest match" in w for w in result.get("warnings", []))
