"""Synthetic large-repo benchmark for Whyloom.

Generates a repository of N Python modules with realistic cross-file imports and
calls, then measures cold-index time, incremental-reindex time, retrieval
latency, and index size. Use to validate that indexing scales and that retrieval
stays bounded regardless of repo size.

    uv run python scripts/benchmark_scale.py --files 5000
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
import time
import tracemalloc
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.operations import init_project
from whyloom.retrieval import context_packet
from whyloom.store import GraphStore


def _generate(root: Path, files: int) -> None:
    pkg = root / "src" / "app"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    for i in range(files):
        callee = f"mod{(i + 1) % files}"
        (pkg / f"mod{i}.py").write_text(
            f"from app.{callee} import handler{(i + 1) % files}\n\n\n"
            f"def handler{i}(value):\n"
            f"    # WHY: mod{i} normalizes before delegating\n"
            f"    return handler{(i + 1) % files}(value) if value else {i}\n",
            encoding="utf-8",
        )


def benchmark(files: int) -> dict:
    directory = Path(tempfile.mkdtemp())
    root = directory / "repo"
    try:
        gen_start = time.perf_counter()
        _generate(root, files)
        init_project(root)
        gen_ms = (time.perf_counter() - gen_start) * 1000

        tracemalloc.start()
        cold_start = time.perf_counter()
        result = index_project(root, DEFAULT_CONFIG)
        cold_ms = (time.perf_counter() - cold_start) * 1000
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        incr_start = time.perf_counter()
        index_project(root, DEFAULT_CONFIG)  # nothing changed
        incr_ms = (time.perf_counter() - incr_start) * 1000

        db = root / DEFAULT_CONFIG["database"]
        with GraphStore(db, create=False) as store:
            retr_start = time.perf_counter()
            packet = context_packet(store, "normalize before delegating handler")
            retr_ms = (time.perf_counter() - retr_start) * 1000

        return {
            "files": files,
            "generate_ms": round(gen_ms, 1),
            "cold_index_ms": round(cold_ms, 1),
            "incremental_index_ms": round(incr_ms, 1),
            "retrieval_ms": round(retr_ms, 2),
            "nodes_written": result["nodes_written"],
            "edges_written": result["edges_written"],
            "peak_mem_mb": round(peak / 1_000_000, 1),
            "db_size_mb": round(db.stat().st_size / 1_000_000, 1),
            "retrieval_evidence_count": len(packet["evidence"]),
        }
    finally:
        shutil.rmtree(directory, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--files", type=int, default=2000)
    args = parser.parse_args()
    import json

    print(json.dumps(benchmark(args.files), indent=2))
