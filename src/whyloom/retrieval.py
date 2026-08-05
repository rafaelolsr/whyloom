from __future__ import annotations

import heapq
from itertools import count
from pathlib import Path

from .store import GraphStore

# Record types that can govern implementation intent.
GOVERNING_TYPES = frozenset({"Decision", "Constraint", "Architecture", "Incident"})
# Statuses that make a governing record authoritative (vs proposed).
# A record governs when its lifecycle is authoritative. Includes the OKF value
# (stable) and the legacy whyloom values it maps from.
ACCEPTED_STATUSES = frozenset({"stable", "accepted", "implemented"})

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
        authority = 1.2 if status in ACCEPTED_STATUSES else 1.0
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


def _looks_inferred(record: dict) -> bool:
    """Whether a record's content was produced by a non-human. Prefers the explicit
    OKF `generated.by` (a human actor starts with `human:`); falls back to the
    legacy signals (an INFERRED id or a machine confidence score) for records
    written before OKF fields existed."""
    generated = record.get("data", {}).get("generated")
    if isinstance(generated, dict) and generated.get("by"):
        return not str(generated["by"]).startswith("human:")
    if "INFERRED" in record.get("id", "").upper():
        return True
    return record.get("data", {}).get("confidence") is not None


def context_packet(store: GraphStore, task: str, max_depth: int = 2, max_items: int = 20) -> dict:
    candidates = [item for item in store.search(task, max(50, max_items * 3)) if item["type"] in SEED_PRIORITY]

    def demote(item: dict) -> bool:
        # Tests/config/poc are weak seeds — push them after real sources, but keep
        # search's already-diversified order otherwise. Re-sorting purely by
        # lexical_rank here would undo the per-file diversification search applied,
        # re-clustering one symbol-dense file's hits and burying sibling files.
        path = (item.get("path") or "").casefold()
        return (
            item["type"] == "ConfigKey"
            or path.startswith(("tests/", "evals/"))
            or "/tests/" in path
            or "/poc/" in path
        )

    # Stable partition preserves search order within each group.
    candidates = [c for c in candidates if not demote(c)] + [c for c in candidates if demote(c)]
    seeds = candidates[: min(max_items, 5)]
    # A governing record links to a File node (APPLIES_TO/IMPLEMENTS/CONSTRAINED_BY),
    # but lexical search usually matches the Symbols *inside* a file, not the File
    # node itself. Left alone, the record sits at depth 3 (Symbol→File→Record) —
    # past max_depth — and sibling symbols exhaust the item budget first. Promote
    # each seed symbol's containing File to a seed so its record is reached at
    # depth 1. Deterministic: the File id is derived from the symbol's source path.
    seed_ids = {seed["id"] for seed in seeds}
    for seed in list(seeds):
        source_path = seed.get("source_path") or (seed.get("path") if seed["type"] == "Symbol" else None)
        if not source_path:
            continue
        file_node = store.node(f"file:{source_path}") or store.node(source_path)
        if file_node and file_node["type"] == "File" and file_node["id"] not in seed_ids:
            seeds.append(file_node)
            seed_ids.add(file_node["id"])
    items = traverse(store, seeds, max_depth=max_depth, max_items=max_items)
    records = [item for item in items if item["type"] in GOVERNING_TYPES]
    governing = [item for item in records if item.get("data", {}).get("status") in ACCEPTED_STATUSES]
    # Proposed records carry day-one rationale but are not yet trusted; surface
    # them separately so the caller sees the why without mistaking it for
    # authoritative intent.
    proposed = [item for item in records if item.get("data", {}).get("status") in {"draft", "proposed"}]
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
    # Trust check: an accepted record that looks agent-authored (inference
    # signals: an INFERRED id or a machine confidence score) may not have passed
    # human review. Surface it — do not block — so the reader confirms provenance.
    unverified = [r["id"] for r in governing if _looks_inferred(r)]
    if unverified:
        warnings.append(
            f"{len(unverified)} accepted record(s) appear agent-authored ({', '.join(unverified[:3])}) — "
            "confirm a human reviewed them before relying on them."
        )
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
        # Include files reached directly and the files that contain matched
        # symbols, so a symbol hit always surfaces its file.
        "files": sorted(
            {item["path"] for item in packet["files"] if item.get("path")}
            | {item["path"] for item in packet["evidence"] if item["type"] == "Symbol" and item.get("path")}
        ),
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

    # Impact must be PRECISE, not lexical. A weighted graph walk (traverse) wanders
    # across loosely-related nodes via any edge and inflates "1 real caller" into
    # dozens of keyword-adjacent false positives. Instead follow only true
    # reverse-dependency edges into the target and the symbols it contains:
    # something CALLS/IMPORTS/INHERITS/REFERENCES/CONSTRAINED_BY it, or a governing
    # record APPLIES_TO it.
    DEPENDENCY_EDGES = {"CALLS", "IMPORTS", "INHERITS", "REFERENCES", "CONSTRAINED_BY", "APPLIES_TO", "IMPLEMENTS"}

    # The change surface: the target plus the code it directly reaches.
    surface: dict[str, dict] = {node["id"]: {**node, "distance": 0}}
    if node["type"] in GOVERNING_TYPES:
        # A record's change surface is the files/symbols it governs (APPLIES_TO/
        # IMPLEMENTS), so impact on a decision names the code it constrains.
        for neighbor in store.neighbors(node["id"]):
            edge, other = neighbor["edge"], neighbor["node"]
            if edge["type"] in {"APPLIES_TO", "IMPLEMENTS"} and edge["source"] == node["id"]:
                surface[other["id"]] = {**other, "via": edge, "distance": 1}

    # Expand every file on the surface into the symbols it contains.
    for sid in list(surface):
        if surface[sid]["type"] != "File":
            continue
        for neighbor in store.neighbors(sid):
            edge, other = neighbor["edge"], neighbor["node"]
            if edge["type"] == "CONTAINS" and edge["source"] == sid and other["type"] == "Symbol" and other["id"] not in surface:
                surface[other["id"]] = {**other, "distance": surface[sid]["distance"]}

    # Anything with a dependency edge pointing AT the surface is affected.
    affected: dict[str, dict] = {}
    records: list[dict] = []
    for sid, snode in surface.items():
        for neighbor in store.neighbors(sid):
            edge, other = neighbor["edge"], neighbor["node"]
            if edge["type"] not in DEPENDENCY_EDGES or edge["target"] != sid:
                continue  # only edges pointing INTO the surface (dependents)
            if other["id"] in surface or other["id"] in affected:
                continue
            entry = {**other, "via": edge, "distance": 1}
            if other["type"] in {"Decision", "Constraint", "Architecture", "Incident"}:
                records.append(entry)
            else:
                affected[other["id"]] = entry

    contained = [v for v in surface.values() if v["id"] != node["id"] and v["type"] == "Symbol"]
    all_items = list(surface.values()) + list(affected.values()) + records
    # Files affected: governed files on the surface (record target) + dependent files.
    files = [v for v in surface.values() if v["id"] != node["id"] and v["type"] == "File"]
    files += [i for i in affected.values() if i["type"] == "File"]
    # Symbols on the change surface (contained) plus dependent symbols.
    symbols = contained + [i for i in affected.values() if i["type"] == "Symbol"]
    callers = [
        {"id": i["id"], "label": i["label"], "path": i.get("path"), "via": (i.get("via") or {}).get("type")}
        for i in affected.values()
        if i["type"] == "Symbol" and (i.get("via") or {}).get("type") in {"CALLS", "IMPORTS"}
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


def _enrich_governing(records: list[dict], root: Path | None, config: dict | None) -> None:
    """Attach human-readable detail (title, Context/Decision/Consequences prose,
    open questions, targets) to each governing record in place by reading its
    source file. Index nodes hold only frontmatter, not the body, so a structured
    explanation must consult the record on disk. Best-effort: a missing or
    unparseable file simply leaves the record with its index-level fields."""
    if root is None or config is None:
        return
    from .records import discover_records, record_sections

    parsed, _ = discover_records(root, config["records_dir"])
    by_id = {record.id: record for record in parsed}
    for item in records:
        record = by_id.get(item["id"])
        if record is None:
            continue
        sections = record_sections(record.body)
        item["title"] = record.title
        item["status"] = record.status.value
        item["targets"] = record.targets
        item["provenance"] = "agent-authored" if _looks_inferred(item) else "human-authored"
        # Records come in two shapes: decision (Context/Decision/Consequences,
        # or architecture Observation/Inference) and role (Role/Responsibilities/
        # Boundaries). Map both onto the same three display slots so explain renders
        # either kind uniformly.
        item["why"] = sections.get("context") or sections.get("observation") or sections.get("role") or ""
        item["decision"] = (
            sections.get("decision")
            or sections.get("decision inferred from evidence")
            or sections.get("inference")
            or sections.get("responsibilities")
            or ""
        )
        item["consequences"] = sections.get("consequences") or sections.get("boundaries") or ""
        item["open_questions"] = record.open_questions


def explain_target(
    store: GraphStore,
    target: str,
    max_depth: int = 2,
    max_items: int = 20,
    root: Path | None = None,
    config: dict | None = None,
) -> dict:
    node = _resolve_node(store, target)
    if node is None:
        return {"target": target, "found": False, "evidence": [], "warnings": ["Target not found in the graph."]}
    items = traverse(store, [node], max_depth=max_depth, max_items=max_items)
    governing = [item for item in items if item["type"] in GOVERNING_TYPES]
    _enrich_governing(governing, root, config)
    return {
        "target": target,
        "found": True,
        "node": node,
        "governing_records": governing,
        "related_code": [item for item in items if item["type"] in {"File", "Symbol"} and item["id"] != node["id"]],
        "evidence": items,
        "knowledge_gaps": [] if any(item["type"] in GOVERNING_TYPES for item in items) else ["No governing record is linked to this target."],
    }
