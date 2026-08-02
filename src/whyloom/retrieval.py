from __future__ import annotations

import heapq
from itertools import count

from .store import GraphStore

# Record types that can govern implementation intent.
GOVERNING_TYPES = frozenset({"Decision", "Constraint"})
# Statuses that make a governing record authoritative (vs proposed).
ACCEPTED_STATUSES = frozenset({"accepted", "implemented"})

EDGE_WEIGHTS = {
    "APPLIES_TO": 1.0,
    "IMPLEMENTS": 1.0,
    "CONSTRAINED_BY": 1.0,
    "SUPERSEDES": 0.9,
    "CONTAINS": 0.8,
    "IMPORTS": 0.75,
    "CALLS": 0.9,
    "INHERITS": 0.85,
    "REFERENCES": 0.65,
    "CONFIGURES": 0.7,
    "MEMBER_OF": 0.55,
    # Rationale comments are advisory evidence: reachable, but weighted below
    # structural edges so they never outrank governed records or code links.
    "ANNOTATES": 0.5,
}

SEED_PRIORITY = {
    "Decision": 0,
    "Constraint": 0,
    "Architecture": 1,
    "Incident": 1,
    "File": 2,
    "Symbol": 3,
    "ConfigKey": 3,
    "Community": 4,
    # Below code and records: advisory, never authoritative.
    "Rationale": 5,
}


def traverse(store: GraphStore, seeds: list[dict], max_depth: int = 2, max_items: int = 20) -> list[dict]:
    sequence = count()
    queue: list[tuple[float, int, dict, int, dict | None]] = []
    for seed in seeds:
        heapq.heappush(queue, (-1.0, next(sequence), seed, 0, None))
    seen: dict[str, dict] = {}
    while queue and len(seen) < max_items:
        negative_strength, _, node, depth, via = heapq.heappop(queue)
        strength = -negative_strength
        if node["id"] in seen:
            continue
        item = dict(node)
        item["distance"] = depth
        item["via"] = via
        status = item.get("data", {}).get("status")
        authority = 1.2 if status in {"accepted", "implemented"} else 1.0
        item["score"] = round(authority * strength, 4)
        seen[node["id"]] = item
        if depth >= max_depth:
            continue
        neighbors = store.neighbors(node["id"])
        neighbors.sort(
            key=lambda neighbor: (
                -EDGE_WEIGHTS.get(neighbor["edge"]["type"], 0.0),
                SEED_PRIORITY.get(neighbor["node"]["type"], 10),
                neighbor["node"]["label"],
            )
        )
        for neighbor in neighbors:
            edge = neighbor["edge"]
            if edge["type"] not in EDGE_WEIGHTS:
                continue
            next_node = neighbor["node"]
            if next_node["id"] not in seen:
                direction_factor = 1.0 if edge["source"] == node["id"] else 0.85
                next_strength = strength * EDGE_WEIGHTS[edge["type"]] * direction_factor
                heapq.heappush(
                    queue,
                    (-next_strength, next(sequence), next_node, depth + 1, edge),
                )
    return sorted(seen.values(), key=lambda item: (-item["score"], item["type"], item["label"]))[:max_items]


def context_packet(store: GraphStore, task: str, max_depth: int = 2, max_items: int = 20) -> dict:
    candidates = [item for item in store.search(task, max(50, max_items * 3)) if item["type"] in SEED_PRIORITY]
    def source_penalty(item: dict) -> float:
        path = (item.get("path") or "").casefold()
        penalty = 2.0 if item["type"] == "ConfigKey" else 0.0
        if path.startswith(("tests/", "evals/")) or "/tests/" in path or "/poc/" in path:
            penalty += 5.0
        return penalty

    candidates.sort(
        key=lambda item: (
            item.get("lexical_rank", 0.0) + source_penalty(item),
            SEED_PRIORITY[item["type"]],
            item["label"],
        )
    )
    seeds = candidates[: min(max_items, 5)]
    items = traverse(store, seeds, max_depth=max_depth, max_items=max_items)
    records = [item for item in items if item["type"] in GOVERNING_TYPES]
    governing = [item for item in records if item.get("data", {}).get("status") in ACCEPTED_STATUSES]
    # Proposed records carry day-one rationale but are not yet trusted; surface
    # them separately so the caller sees the why without mistaking it for
    # authoritative intent.
    proposed = [item for item in records if item.get("data", {}).get("status") == "proposed"]
    files = [item for item in items if item["type"] == "File"]
    communities = [item for item in items if item["type"] == "Community"]
    warnings: list[str] = []
    if not seeds:
        warnings.append("No lexical evidence matched the task.")
    if not governing and proposed:
        warnings.append(
            f"No accepted record yet; {len(proposed)} proposed record(s) carry unreviewed rationale — review before trusting."
        )
    elif not governing:
        warnings.append("No accepted decision or constraint was found for this task.")
    return {
        "task": task,
        "governing_records": governing,
        "proposed_records": proposed,
        "files": files,
        "communities": communities,
        "evidence": items,
        "warnings": warnings,
        "unresolved_questions": ["Is missing rationale intentional?"] if not governing else [],
    }


def compact_context_packet(packet: dict) -> dict:
    return {
        "task": packet["task"],
        "governing_records": [
            {
                "id": item["id"],
                "type": item["type"],
                "title": item["label"],
                "path": item["path"],
                "status": item.get("data", {}).get("status"),
            }
            for item in packet["governing_records"]
        ],
        "proposed_records": [
            {
                "id": item["id"],
                "type": item["type"],
                "title": item["label"],
                "path": item["path"],
                "status": "proposed",
            }
            for item in packet.get("proposed_records", [])
        ],
        "files": sorted({item["path"] for item in packet["files"] if item.get("path")}),
        "symbols": [
            {
                "id": item["id"],
                "name": item["label"],
                "path": item.get("path"),
                "line": item.get("data", {}).get("line"),
            }
            for item in packet["evidence"]
            if item["type"] == "Symbol"
        ],
        "relationships": [
            item["via"]
            for item in packet["evidence"]
            if item.get("via") and item["via"].get("type") != "CONTAINS"
        ],
        "communities": [item["label"] for item in packet.get("communities", [])],
        "warnings": packet["warnings"],
        "unresolved_questions": packet["unresolved_questions"],
    }


def _resolve_node(store: GraphStore, target: str) -> dict | None:
    """Resolve a user-supplied target to a graph node by id, file path, or
    lexical search — the same resolution explain and impact use."""
    node = store.node(target) or store.node(f"file:{target}")
    if node is None:
        matches = store.search(target, 1)
        node = matches[0] if matches else None
    return node


def impact_analysis(store: GraphStore, target: str, max_depth: int = 2, max_items: int = 20) -> dict:
    """Assess what a change to ``target`` affects, scoped to concrete entities.

    Traversal from a record reaches the files it governs; this expands those
    files into the symbols they contain so the answer names specific code, not
    just files. Results are grouped by how they are affected: directly governed
    records, the files/symbols that carry the change, and the symbols that call
    into affected symbols (downstream callers)."""
    node = _resolve_node(store, target)
    if node is None:
        return {"target": target, "found": False, "affected": {}, "evidence": [], "warnings": ["Target not found in the graph."]}

    items = traverse(store, [node], max_depth=max_depth, max_items=max_items)
    seen_ids = {item["id"] for item in items}

    # Expand affected files into their contained symbols, and pull direct callers
    # of affected symbols, so impact names concrete code rather than whole files.
    expanded: list[dict] = []
    for item in items:
        if item["type"] not in {"File", "Symbol"}:
            continue
        for neighbor in store.neighbors(item["id"]):
            edge, other = neighbor["edge"], neighbor["node"]
            if other["id"] in seen_ids:
                continue
            # File -> contained Symbol, or Symbol <- CALLS (a downstream caller).
            is_contained = edge["type"] == "CONTAINS" and other["type"] == "Symbol"
            is_caller = edge["type"] == "CALLS" and edge["target"] == item["id"]
            if is_contained or is_caller:
                seen_ids.add(other["id"])
                expanded.append({**other, "via": edge, "distance": item.get("distance", 0) + 1})

    all_items = items + expanded
    records = [i for i in all_items if i["type"] in {"Decision", "Constraint", "Architecture", "Incident"}]
    files = [i for i in all_items if i["type"] == "File"]
    symbols = [i for i in all_items if i["type"] == "Symbol"]
    callers = [
        {"id": i["id"], "label": i["label"], "path": i.get("path"), "via": (i.get("via") or {}).get("type")}
        for i in symbols
        if (i.get("via") or {}).get("type") == "CALLS"
    ]

    return {
        "target": target,
        "found": True,
        "affected": {
            "records": records,
            "files": [{"id": f["id"], "path": f.get("path") or f["label"]} for f in files],
            "symbols": [{"id": s["id"], "name": s["label"], "path": s.get("path")} for s in symbols],
            "downstream_callers": callers,
        },
        "counts": {"records": len(records), "files": len(files), "symbols": len(symbols), "callers": len(callers)},
        "evidence": all_items,
        "warnings": [],
    }


def find_path(store: GraphStore, source: str, target: str, max_hops: int = 8) -> dict:
    """Return the shortest relationship path between two entities, hop by hop.

    Breadth-first over the undirected graph, so the first path found is minimal
    in hops. Each hop names the edge type and its provenance/confidence so an
    agent can judge how much to trust the connection."""
    start = _resolve_node(store, source)
    end = _resolve_node(store, target)
    warnings: list[str] = []
    if start is None:
        warnings.append(f"Source not found in the graph: {source}")
    if end is None:
        warnings.append(f"Target not found in the graph: {target}")
    if start is None or end is None:
        return {"source": source, "target": target, "found": False, "hops": [], "warnings": warnings}

    if start["id"] == end["id"]:
        return {
            "source": source,
            "target": target,
            "found": True,
            "length": 0,
            "endpoints": {"source": start["id"], "target": end["id"]},
            "hops": [],
            "warnings": ["Source and target resolve to the same node."],
        }

    # BFS, recording the edge taken to reach each node so the path can be rebuilt.
    previous: dict[str, tuple[str, dict]] = {}
    visited = {start["id"]}
    frontier = [start["id"]]
    depth = 0
    reached = False
    while frontier and depth < max_hops and not reached:
        depth += 1
        next_frontier: list[str] = []
        for node_id in frontier:
            for neighbor in store.neighbors(node_id):
                neighbor_id = neighbor["node"]["id"]
                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)
                previous[neighbor_id] = (node_id, neighbor)
                if neighbor_id == end["id"]:
                    reached = True
                    break
                next_frontier.append(neighbor_id)
            if reached:
                break
        frontier = next_frontier

    if end["id"] not in previous:
        return {
            "source": source,
            "target": target,
            "found": False,
            "hops": [],
            "warnings": warnings + [f"No path within {max_hops} hops between the resolved nodes."],
        }

    # Rebuild the path from end back to start, then reverse.
    chain: list[dict] = []
    cursor = end["id"]
    while cursor != start["id"]:
        came_from, neighbor = previous[cursor]
        edge = neighbor["edge"]
        chain.append(
            {
                "from": came_from,
                "to": cursor,
                "type": edge["type"],
                "provenance": edge["provenance"],
                "confidence": edge["confidence"],
                "evidence": edge["evidence"],
                "label": neighbor["node"]["label"],
            }
        )
        cursor = came_from
    chain.reverse()
    return {
        "source": source,
        "target": target,
        "found": True,
        "length": len(chain),
        "endpoints": {"source": start["id"], "target": end["id"]},
        "hops": chain,
        "warnings": warnings,
    }


def explain_target(store: GraphStore, target: str, max_depth: int = 2, max_items: int = 20) -> dict:
    node = _resolve_node(store, target)
    if node is None:
        return {"target": target, "found": False, "evidence": [], "warnings": ["Target not found in the graph."]}
    items = traverse(store, [node], max_depth=max_depth, max_items=max_items)
    return {
        "target": target,
        "found": True,
        "node": node,
        "governing_records": [item for item in items if item["type"] in GOVERNING_TYPES],
        "related_code": [item for item in items if item["type"] in {"File", "Symbol"} and item["id"] != node["id"]],
        "evidence": items,
        "knowledge_gaps": [] if any(item["type"] in GOVERNING_TYPES for item in items) else ["No governing record is linked to this target."],
    }
