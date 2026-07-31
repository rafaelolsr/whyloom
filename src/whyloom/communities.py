from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from pathlib import PurePosixPath
from typing import Any

from .models import GraphEdge, GraphNode


def _signature(paths: list[str]) -> str:
    return hashlib.sha256("\0".join(paths).encode()).hexdigest()[:16]


def _scope(path: str) -> str:
    parts = PurePosixPath(path).parts
    if not parts:
        return "root"
    if parts[0] in {"apps", "lib", "packages", "services", "src"} and len(parts) > 2:
        return "/".join(parts[:2])
    return parts[0]


def build_communities(nodes: list[GraphNode], edges: list[GraphEdge], digest: str) -> tuple[list[GraphNode], list[GraphEdge], dict[str, Any]]:
    node_path = {node.id: node.path for node in nodes if node.path and node.type in {"File", "Symbol", "ConfigKey"}}
    files = sorted({path for path in node_path.values() if path})
    weights: Counter[tuple[str, str]] = Counter()
    cross_edges: list[dict[str, Any]] = []
    for edge in edges:
        source_path = node_path.get(edge.source)
        target_path = node_path.get(edge.target)
        if not source_path or not target_path or source_path == target_path:
            continue
        pair = tuple(sorted((source_path, target_path)))
        weights[pair] += 1
    scoped: dict[str, set[str]] = defaultdict(set)
    for path in files:
        scoped[_scope(path)].add(path)
    # Attach singleton scopes to the most strongly connected neighbouring scope.
    for scope in sorted(list(scoped)):
        members = scoped.get(scope, set())
        if len(members) != 1:
            continue
        member = next(iter(members))
        connections: Counter[str] = Counter()
        for (source, target), weight in weights.items():
            if source == member:
                connections[_scope(target)] += weight
            elif target == member:
                connections[_scope(source)] += weight
        candidates = [(count, candidate) for candidate, count in connections.items() if candidate != scope and candidate in scoped]
        if candidates:
            _, destination = max(candidates, key=lambda item: (item[0], item[1]))
            scoped[destination].update(members)
            del scoped[scope]
    ordered = sorted((sorted(group) for group in scoped.values()), key=lambda group: (-len(group), group[0]))
    community_nodes: list[GraphNode] = []
    membership_edges: list[GraphEdge] = []
    file_community: dict[str, str] = {}
    node_counts = Counter(node.path for node in nodes if node.path)
    record_targets = defaultdict(list)
    for node in nodes:
        if node.type in {"Decision", "Constraint", "Architecture", "Incident"}:
            for target in node.data.get("targets", []):
                record_targets[target].append(node.id)
    manifest_communities: list[dict[str, Any]] = []
    for members in ordered:
        signature = _signature(members)
        community_id = f"community:{signature}"
        for member in members:
            file_community[member] = community_id
        roots = Counter(path.split("/")[0] for path in members)
        dominant_root = min(roots, key=lambda item: (-roots[item], item))
        linked_records = sorted({record for path in members for record in record_targets.get(path, [])})
        symbol_count = sum(node_counts[path] - 1 for path in members)
        community_nodes.append(
            GraphNode(
                id=community_id,
                type="Community",
                label=dominant_root,
                source_path="@communities",
                source_hash=digest,
                data={"signature": signature, "files": len(members), "symbols": max(0, symbol_count)},
            )
        )
        for member in members:
            membership_edges.append(
                GraphEdge(
                    source=f"file:{member}",
                    target=community_id,
                    type="MEMBER_OF",
                    origin="structural-community",
                    provenance="INFERRED",
                    evidence=f"community:{signature}",
                    confidence=0.8,
                    source_path="@communities",
                    source_hash=digest,
                )
            )
        manifest_communities.append(
            {
                "id": community_id,
                "signature": signature,
                "label": dominant_root,
                "files": members,
                "file_count": len(members),
                "symbol_count": max(0, symbol_count),
                "record_ids": linked_records,
                "rationale_status": "recorded" if linked_records else "missing",
            }
        )
    for edge in edges:
        source_path = node_path.get(edge.source)
        target_path = node_path.get(edge.target)
        source_community = file_community.get(source_path or "")
        target_community = file_community.get(target_path or "")
        if source_community and target_community and source_community != target_community:
            cross_edges.append(
                {
                    "source": edge.source,
                    "target": edge.target,
                    "type": edge.type,
                    "source_community": source_community,
                    "target_community": target_community,
                    "evidence": edge.evidence,
                }
            )
    manifest = {
        "version": 1,
        "authoritative": False,
        "indexed_files": len(files),
        "communities": manifest_communities,
        "cross_community_relationships": cross_edges[:200],
        "coverage": {
            "files_assigned": sum(item["file_count"] for item in manifest_communities),
            "files_total": len(files),
            "communities_total": len(manifest_communities),
            "communities_with_records": sum(item["rationale_status"] == "recorded" for item in manifest_communities),
            "communities_missing_rationale": sum(item["rationale_status"] == "missing" for item in manifest_communities),
        },
    }
    return community_nodes, membership_edges, manifest
