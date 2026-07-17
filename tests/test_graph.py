import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import compact_context_packet, context_packet, explain_target
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


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
    assert version == 2
    assert {row[0] for row in imports} == {"module:src/sample/auth.py:hashlib"}

    compact = compact_context_packet(packet)
    assert compact["files"] == ["src/sample/auth.py"]
    assert {item["id"] for item in compact["governing_records"]} == {"DEC-0001", "CON-0001"}
    assert "evidence" not in compact
