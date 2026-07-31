from __future__ import annotations

import heapq
from itertools import count

from .store import GraphStore

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
    governing = [item for item in items if item["type"] in {"Decision", "Constraint"} and item.get("data", {}).get("status") in {"accepted", "implemented"}]
    files = [item for item in items if item["type"] == "File"]
    communities = [item for item in items if item["type"] == "Community"]
    warnings: list[str] = []
    if not seeds:
        warnings.append("No lexical evidence matched the task.")
    if not governing:
        warnings.append("No accepted decision or constraint was found for this task.")
    return {
        "task": task,
        "governing_records": governing,
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


def explain_target(store: GraphStore, target: str, max_depth: int = 2, max_items: int = 20) -> dict:
    node = store.node(target) or store.node(f"file:{target}")
    if node is None:
        matches = store.search(target, 1)
        node = matches[0] if matches else None
    if node is None:
        return {"target": target, "found": False, "evidence": [], "warnings": ["Target not found in the graph."]}
    items = traverse(store, [node], max_depth=max_depth, max_items=max_items)
    return {
        "target": target,
        "found": True,
        "node": node,
        "governing_records": [item for item in items if item["type"] in {"Decision", "Constraint"}],
        "related_code": [item for item in items if item["type"] in {"File", "Symbol"} and item["id"] != node["id"]],
        "evidence": items,
        "knowledge_gaps": [] if any(item["type"] in {"Decision", "Constraint"} for item in items) else ["No governing record is linked to this target."],
    }
