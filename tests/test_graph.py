import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import compact_context_packet, context_packet, explain_target, find_path
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_find_path_between_file_and_record(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = find_path(store, "src/sample/auth.py", "DEC-0001")
    assert result["found"]
    assert result["length"] >= 1
    assert result["endpoints"]["target"] == "DEC-0001"
    # Every hop names an edge type and provenance so the connection is auditable.
    for hop in result["hops"]:
        assert hop["type"]
        assert hop["provenance"] in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def test_find_path_missing_endpoint(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = find_path(store, "src/sample/auth.py", "does-not-exist-xyz")
    assert not result["found"]
    assert result["warnings"]


def test_find_path_same_node(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = find_path(store, "src/sample/auth.py", "src/sample/auth.py")
    assert result["found"]
    assert result["length"] == 0


def test_index_context_and_explain(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    first = index_project(root, DEFAULT_CONFIG)
    second = index_project(root, DEFAULT_CONFIG)
    assert first["nodes_written"] >= 4
    assert first["indexed"]
    assert first["edges_written"] >= 4
    assert not second["changed"]
    assert second["unchanged"]

    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        packet = context_packet(store, "change token storage credentials")
        explanation = explain_target(store, "src/sample/auth.py")

    assert {item["id"] for item in packet["governing_records"]} == {"DEC-0001", "CON-0001"}
    assert explanation["found"]
    assert {item["id"] for item in explanation["governing_records"]} == {"DEC-0001", "CON-0001"}

    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        version = store.connection.execute("SELECT MAX(version) FROM migration_history").fetchone()[0]
        imports = store.connection.execute("SELECT target FROM edges WHERE type = 'IMPORTS'").fetchall()
    assert version == 3
    assert {row[0] for row in imports} == {"module-ref:src/sample/auth.py:hashlib"}

    compact = compact_context_packet(packet)
    assert compact["files"] == ["src/sample/auth.py"]
    assert {item["id"] for item in compact["governing_records"]} == {"DEC-0001", "CON-0001"}
    assert "evidence" not in compact


def test_impact_analysis_expands_files_to_symbols(tmp_path):
    from whyloom.retrieval import impact_analysis

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = impact_analysis(store, "CON-0001")
    assert result["found"]
    # Impact names concrete entities: the governed file's symbols, not just files.
    assert result["affected"]["symbols"]
    assert result["counts"]["symbols"] >= 1
    # Grouped output separates records, files, symbols, and callers.
    assert set(result["affected"]) == {"records", "files", "symbols", "downstream_callers"}


def test_impact_analysis_missing_target(tmp_path):
    from whyloom.retrieval import impact_analysis

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = impact_analysis(store, "does-not-exist-xyz")
    assert not result["found"]
    assert result["warnings"]
