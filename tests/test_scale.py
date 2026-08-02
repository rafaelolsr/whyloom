"""Fast scale smoke test: a few hundred files index and retrieve within bounds.

The full benchmark lives in scripts/benchmark_scale.py; this keeps CI honest that
indexing scales and retrieval stays bounded without a slow run."""

import time

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.operations import init_project
from whyloom.retrieval import context_packet
from whyloom.store import GraphStore


def _generate(root, files):
    pkg = root / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for i in range(files):
        nxt = (i + 1) % files
        (pkg / f"mod{i}.py").write_text(
            f"from app.mod{nxt} import handler{nxt}\n\n\n"
            f"def handler{i}(value):\n    return handler{nxt}(value) if value else {i}\n",
            encoding="utf-8",
        )


def test_indexes_hundreds_of_files_and_retrieval_stays_bounded(tmp_path):
    root = tmp_path / "repo"
    _generate(root, 300)
    init_project(root)
    result = index_project(root, DEFAULT_CONFIG)
    assert result["indexed"]
    assert result["nodes_written"] >= 300

    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        start = time.perf_counter()
        packet = context_packet(store, "handler delegates to next module")
        elapsed = time.perf_counter() - start
    # Retrieval is bounded regardless of repo size.
    assert len(packet["evidence"]) <= DEFAULT_CONFIG["max_items"]
    assert elapsed < 1.0  # generous ceiling; typically single-digit ms


def test_incremental_reindex_is_cheap(tmp_path):
    root = tmp_path / "repo"
    _generate(root, 200)
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    # Second index with no changes writes nothing new.
    second = index_project(root, DEFAULT_CONFIG)
    assert not second["changed"]
    assert second["unchanged"]
