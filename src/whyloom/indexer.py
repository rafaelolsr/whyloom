from __future__ import annotations

import time
from fnmatch import fnmatch
from pathlib import Path

from .codegraph import extract_python, source_hash
from .config import resolve_repository_path
from .migrations import INDEX_FORMAT_VERSION
from .models import Diagnostic, GraphEdge, GraphNode, ProjectRecord
from .records import discover_records
from .store import GraphStore


def _record_graph(record: ProjectRecord, root: Path) -> tuple[list[GraphNode], list[GraphEdge], list[tuple[str, str, str, str]]]:
    node = GraphNode(
        id=record.id,
        type=record.type.value.title(),
        label=record.title,
        path=record.path.as_posix(),
        source_path=record.path.as_posix(),
        source_hash=record.source_hash,
        data={
            "status": record.status.value,
            "date": record.date.isoformat() if record.date else None,
            "targets": record.targets,
            "constraints": record.constraints,
            "supersedes": record.supersedes,
        },
    )
    edges: list[GraphEdge] = []
    for target in record.targets:
        target_id = f"file:{target}"
        edges.append(
            GraphEdge(
                source=record.id,
                target=target_id,
                type="APPLIES_TO",
                origin="record-frontmatter",
                evidence=record.path.as_posix(),
                source_path=record.path.as_posix(),
                source_hash=record.source_hash,
            )
        )
        reverse_type = "CONSTRAINED_BY" if record.type.value == "constraint" else "IMPLEMENTS"
        edges.append(
            GraphEdge(
                source=target_id,
                target=record.id,
                type=reverse_type,
                origin="record-frontmatter",
                evidence=record.path.as_posix(),
                source_path=record.path.as_posix(),
                source_hash=record.source_hash,
            )
        )
    for constraint in record.constraints:
        edges.append(
            GraphEdge(
                source=record.id,
                target=constraint,
                type="CONSTRAINED_BY",
                origin="record-frontmatter",
                evidence=record.path.as_posix(),
                source_path=record.path.as_posix(),
                source_hash=record.source_hash,
            )
        )
    for superseded in record.supersedes:
        edges.append(
            GraphEdge(
                source=record.id,
                target=superseded,
                type="SUPERSEDES",
                origin="record-frontmatter",
                evidence=record.path.as_posix(),
                source_path=record.path.as_posix(),
                source_hash=record.source_hash,
            )
        )
    document = (record.id, f"{record.id} {record.title}", record.body, record.path.as_posix())
    return [node], edges, [document]


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pattern) or Path(path).match(pattern) for pattern in patterns)


def discover_code_paths(root: Path, config: dict) -> tuple[list[Path], list[Diagnostic]]:
    discovered: set[Path] = set()
    diagnostics: list[Diagnostic] = []
    for pattern in config["include"]:
        for path in root.glob(pattern):
            if not path.is_file() or path.is_symlink():
                continue
            rel = path.relative_to(root).as_posix()
            if _matches(rel, config["exclude"]):
                continue
            if path.suffix != ".py":
                diagnostics.append(
                    Diagnostic(
                        code="LANG001",
                        severity="warning",
                        message=f"no language adapter for {path.suffix or 'extensionless files'}",
                        path=rel,
                    )
                )
                continue
            discovered.add(path)
    return sorted(discovered), diagnostics


def index_project(root: Path, config: dict) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"repository root does not exist or is not a directory: {root}")
    started = time.perf_counter()
    db_path = resolve_repository_path(root, config["database"])
    resolve_repository_path(root, config["records_dir"])
    records, diagnostics = discover_records(root, config["records_dir"])
    changed: list[str] = []
    unchanged: list[str] = []
    present: set[str] = set()
    node_count = 0
    edge_count = 0

    python_paths, discovery_diagnostics = discover_code_paths(root, config)
    diagnostics.extend(discovery_diagnostics)
    if any(item.severity == "error" for item in diagnostics):
        return {
            "indexed": False,
            "root": str(root),
            "database": str(db_path),
            "changed": [],
            "unchanged": [],
            "removed": [],
            "nodes_written": 0,
            "edges_written": 0,
            "records": len(records),
            "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
            "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    with GraphStore(db_path) as store, store.transaction():
        for path in sorted(python_paths):
            rel = path.relative_to(root).as_posix()
            present.add(rel)
            digest = source_hash(path)
            if store.source_hash(rel) == digest and store.source_index_version(rel) == INDEX_FORMAT_VERSION:
                unchanged.append(rel)
                continue
            nodes, edges, warnings = extract_python(path, root)
            diagnostics.extend(warnings)
            documents = [(node.id, node.label, "", node.path or rel) for node in nodes]
            store.replace_source(rel, digest, "python", INDEX_FORMAT_VERSION, nodes, edges, documents)
            changed.append(rel)
            node_count += len(nodes)
            edge_count += len(edges)

        for record in records:
            rel = record.path.as_posix()
            present.add(rel)
            if store.source_hash(rel) == record.source_hash and store.source_index_version(rel) == INDEX_FORMAT_VERSION:
                unchanged.append(rel)
                continue
            nodes, edges, documents = _record_graph(record, root)
            store.replace_source(rel, record.source_hash, "record", INDEX_FORMAT_VERSION, nodes, edges, documents)
            changed.append(rel)
            node_count += len(nodes)
            edge_count += len(edges)

        removed = store.remove_missing_sources(present)

    return {
        "indexed": True,
        "root": str(root),
        "database": str(db_path),
        "changed": changed,
        "unchanged": unchanged,
        "removed": removed,
        "nodes_written": node_count,
        "edges_written": edge_count,
        "records": len(records),
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
