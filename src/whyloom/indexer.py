from __future__ import annotations

import hashlib
import json
import os
import time
from fnmatch import fnmatch
from pathlib import Path

from .codegraph import searchable_text, source_hash
from .communities import build_communities
from .config import resolve_repository_path
from .configgraph import extract_config, resolve_config_references
from .languages import Extraction, default_registry
from .locking import index_lock
from .migrations import INDEX_FORMAT_VERSION
from .models import Diagnostic, GraphEdge, GraphNode, ProjectRecord
from .path_policy import is_ignored_directory
from .records import discover_records
from .store import GraphStore

PROJECT_RELATION_SOURCE = "@project-relations"
COMMUNITY_SOURCE = "@communities"
DERIVED_GRAPH_VERSION = 2
_CONFIG_SUFFIXES = {".json", ".yaml", ".yml"}
SUPPORTED_SUFFIXES = default_registry().code_suffixes | _CONFIG_SUFFIXES


def _resolve_target_files(target: str, root: Path, known_files: frozenset[str]) -> list[str]:
    """Resolve a record target to the file paths it governs. A file target maps to
    itself; a directory target expands to every indexed file beneath it. Without
    this expansion a directory target (e.g. `catalog`) links to a phantom
    `file:catalog` node that no file matches, orphaning the record from the code it
    governs — so retrieval never surfaces it and agents fall back to grep."""
    normalized = target.strip("/")
    if normalized in known_files:
        return [normalized]
    if (root / normalized).is_dir():
        prefix = f"{normalized}/"
        contained = sorted(path for path in known_files if path.startswith(prefix))
        if contained:
            return contained
    # Unknown target (missing path, or a file not indexed): keep the literal edge
    # so validation still flags it, rather than silently dropping the link.
    return [normalized]


def _record_graph(
    record: ProjectRecord, root: Path, known_files: frozenset[str] = frozenset()
) -> tuple[list[GraphNode], list[GraphEdge], list[tuple[str, str, str, str]]]:
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
            "confidence": record.confidence.value if record.confidence else None,
            "evidence": [item.model_dump() for item in record.evidence],
            "open_questions": record.open_questions,
            # OKF trust family, so retrieval can read provenance/verification.
            "generated": record.generated.model_dump() if record.generated else None,
            "verified": [item.model_dump() for item in record.verified],
        },
    )
    edges: list[GraphEdge] = []
    reverse_type = "CONSTRAINED_BY" if record.type.value == "constraint" else "IMPLEMENTS"
    resolved_targets: list[str] = []
    for target in record.targets:
        resolved_targets.extend(_resolve_target_files(target, root, known_files))
    for target in dict.fromkeys(resolved_targets):  # de-dupe, preserve order
        target_id = f"file:{target}"
        edges.append(
            GraphEdge(
                source=record.id,
                target=target_id,
                type="APPLIES_TO",
                origin="record-frontmatter",
                provenance="EXTRACTED",
                evidence=record.path.as_posix(),
                source_path=record.path.as_posix(),
                source_hash=record.source_hash,
            )
        )
        edges.append(
            GraphEdge(
                source=target_id,
                target=record.id,
                type=reverse_type,
                origin="record-frontmatter",
                provenance="EXTRACTED",
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
                provenance="EXTRACTED",
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
                provenance="EXTRACTED",
                evidence=record.path.as_posix(),
                source_path=record.path.as_posix(),
                source_hash=record.source_hash,
            )
        )
    document = (record.id, searchable_text(f"{record.id} {record.title}"), record.body, record.path.as_posix())
    return [node], edges, [document]


def _matches(path: str, patterns: list[str]) -> bool:
    return any(_matches_one(path, pattern) for pattern in patterns)


def _matches_one(path: str, pattern: str) -> bool:
    if fnmatch(path, pattern) or Path(path).match(pattern):
        return True
    # `**/` means "any depth including zero", but fnmatch/PurePath.match require
    # at least one directory. Also try the pattern with a leading `**/` stripped
    # so root-level files match include globs like `**/*.py`.
    if pattern.startswith("**/"):
        return fnmatch(path, pattern[3:]) or Path(path).match(pattern[3:])
    return False


def discover_code_paths(root: Path, config: dict) -> tuple[list[Path], list[Diagnostic]]:
    """Discover indexable source files with a single pruning walk.

    Ignored directories (virtualenvs, node_modules, .worktrees, caches, ...) are
    skipped *before* descending into them, so a repo with large vendored trees is
    never traversed. Files are matched against the configured include patterns."""
    discovered: set[Path] = set()
    diagnostics: list[Diagnostic] = []
    includes = config["include"]
    excludes = config["exclude"]

    for current_dir, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune ignored subtrees in place so os.walk does not descend into them.
        dirnames[:] = [d for d in dirnames if not is_ignored_directory(d)]
        for filename in filenames:
            path = Path(current_dir) / filename
            if path.is_symlink() or not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if _matches(rel, excludes):
                continue
            if not any(_matches(rel, [pattern]) for pattern in includes):
                continue
            if path.suffix.casefold() not in SUPPORTED_SUFFIXES:
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


def _project_digest(items: list[tuple[str, str]]) -> str:
    payload = "\0".join(f"{path}:{digest}" for path, digest in sorted(items))
    return hashlib.sha256(payload.encode()).hexdigest()


def _documents(nodes: list[GraphNode], fallback: str) -> list[tuple[str, str, str, str]]:
    return [
        (
            node.id,
            searchable_text(node.label),
            searchable_text(" ".join(str(value) for value in node.data.values() if isinstance(value, str))),
            node.path or fallback,
        )
        for node in nodes
    ]


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def index_project(root: Path, config: dict) -> dict:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"repository root does not exist or is not a directory: {root}")
    started = time.perf_counter()
    db_path = resolve_repository_path(root, config["database"])
    coverage_path = resolve_repository_path(root, ".whyloom/cache/coverage.json")
    resolve_repository_path(root, config["records_dir"])
    records, diagnostics = discover_records(root, config["records_dir"])
    discovered, discovery_diagnostics = discover_code_paths(root, config)
    diagnostics.extend(discovery_diagnostics)

    registry = default_registry()
    extractions_by_adapter: dict[str, list[Extraction]] = {}
    source_graphs: dict[str, tuple[str, str, list[GraphNode], list[GraphEdge]]] = {}
    all_nodes: list[GraphNode] = []
    all_edges: list[GraphEdge] = []
    for path in discovered:
        adapter = registry.for_path(path)
        if adapter is not None:
            extraction = adapter.extract(path, root)
            extractions_by_adapter.setdefault(adapter.name, []).append(extraction)
            diagnostics.extend(extraction.diagnostics)
            source_graphs[extraction.path] = (
                extraction.digest,
                extraction.language,
                extraction.nodes,
                extraction.edges,
            )
            all_nodes.extend(extraction.nodes)
            all_edges.extend(extraction.edges)
        else:
            nodes, edges, warnings = extract_config(path, root)
            rel = path.relative_to(root).as_posix()
            digest = source_hash(path)
            diagnostics.extend(warnings)
            source_graphs[rel] = (digest, "configuration", nodes, edges)
            all_nodes.extend(nodes)
            all_edges.extend(edges)

    known_files = frozenset(path.relative_to(root).as_posix() for path in discovered)
    record_graphs: dict[str, tuple[str, list[GraphNode], list[GraphEdge], list[tuple[str, str, str, str]]]] = {}
    for record in records:
        nodes, edges, documents = _record_graph(record, root, known_files)
        rel = record.path.as_posix()
        record_graphs[rel] = (record.source_hash, nodes, edges, documents)
        all_nodes.extend(nodes)
        all_edges.extend(edges)

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

    digest = _project_digest([(path, values[0]) for path, values in source_graphs.items()])
    resolved_edges: list[GraphEdge] = []
    for adapter in registry.adapters:
        resolved_edges.extend(adapter.resolve_project(extractions_by_adapter.get(adapter.name, [])))
    for edge in resolved_edges:
        edge.source_path = PROJECT_RELATION_SOURCE
        edge.source_hash = digest
    resolved_edges.extend(resolve_config_references(all_nodes, digest))
    all_edges.extend(resolved_edges)
    community_nodes, community_edges, coverage = build_communities(all_nodes, all_edges, digest)

    changed: list[str] = []
    unchanged: list[str] = []
    present = {*source_graphs, *record_graphs, PROJECT_RELATION_SOURCE, COMMUNITY_SOURCE}
    node_count = 0
    edge_count = 0
    lock_path = resolve_repository_path(root, ".whyloom/cache/index.lock")
    with index_lock(lock_path), GraphStore(db_path) as store, store.transaction():
        for rel, (source_digest, kind, nodes, edges) in sorted(source_graphs.items()):
            if store.source_hash(rel) == source_digest and store.source_index_version(rel) == INDEX_FORMAT_VERSION:
                unchanged.append(rel)
                continue
            store.replace_source(rel, source_digest, kind, INDEX_FORMAT_VERSION, nodes, edges, _documents(nodes, rel))
            changed.append(rel)
            node_count += len(nodes)
            edge_count += len(edges)

        for rel, (source_digest, nodes, edges, documents) in sorted(record_graphs.items()):
            if store.source_hash(rel) == source_digest and store.source_index_version(rel) == INDEX_FORMAT_VERSION:
                unchanged.append(rel)
                continue
            store.replace_source(rel, source_digest, "record", INDEX_FORMAT_VERSION, nodes, edges, documents)
            changed.append(rel)
            node_count += len(nodes)
            edge_count += len(edges)

        relation_digest = hashlib.sha256(f"{digest}:relations:{DERIVED_GRAPH_VERSION}".encode()).hexdigest()
        if store.source_hash(PROJECT_RELATION_SOURCE) != relation_digest or store.source_index_version(PROJECT_RELATION_SOURCE) != INDEX_FORMAT_VERSION:
            store.replace_source(PROJECT_RELATION_SOURCE, relation_digest, "derived", INDEX_FORMAT_VERSION, [], resolved_edges, [])
            node_count += 0
            edge_count += len(resolved_edges)

        community_digest = hashlib.sha256(
            (relation_digest + json.dumps(coverage, sort_keys=True)).encode()
        ).hexdigest()
        if store.source_hash(COMMUNITY_SOURCE) != community_digest or store.source_index_version(COMMUNITY_SOURCE) != INDEX_FORMAT_VERSION:
            store.replace_source(
                COMMUNITY_SOURCE,
                community_digest,
                "derived",
                INDEX_FORMAT_VERSION,
                community_nodes,
                community_edges,
                _documents(community_nodes, COMMUNITY_SOURCE),
            )
            node_count += len(community_nodes)
            edge_count += len(community_edges)
        removed = store.remove_missing_sources(present)

    _atomic_json(coverage_path, coverage)
    return {
        "indexed": True,
        "root": str(root),
        "database": str(db_path),
        "coverage_manifest": coverage_path.relative_to(root).as_posix(),
        "coverage": coverage["coverage"],
        "changed": changed,
        "unchanged": unchanged,
        "removed": removed,
        "nodes_written": node_count,
        "edges_written": edge_count,
        "records": len(records),
        "diagnostics": [item.model_dump(mode="json") for item in diagnostics],
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
    }
