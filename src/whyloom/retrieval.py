from __future__ import annotations

from collections import deque

from .store import GraphStore

EDGE_WEIGHTS = {
    "APPLIES_TO": 1.0,
    "IMPLEMENTS": 1.0,
    "CONSTRAINED_BY": 1.0,
    "SUPERSEDES": 0.9,
    "CONTAINS": 0.8,
}

SEED_PRIORITY = {
    "Decision": 0,
    "Constraint": 0,
    "Architecture": 1,
    "Incident": 1,
    "File": 2,
    "Symbol": 3,
}


def traverse(store: GraphStore, seeds: list[dict], max_depth: int = 2, max_items: int = 20) -> list[dict]:
    queue = deque((seed, 0, None) for seed in seeds)
    seen: dict[str, dict] = {}
    while queue and len(seen) < max_items:
        node, depth, via = queue.popleft()
        if node["id"] in seen:
            continue
        item = dict(node)
        item["distance"] = depth
        item["via"] = via
        status = item.get("data", {}).get("status")
        authority = 1.2 if status in {"accepted", "implemented"} else 1.0
        item["score"] = round(authority / (1 + depth), 4)
        seen[node["id"]] = item
        if depth >= max_depth:
            continue
        for neighbor in store.neighbors(node["id"]):
            edge = neighbor["edge"]
            if edge["type"] not in EDGE_WEIGHTS:
                continue
            next_node = neighbor["node"]
            if next_node["id"] not in seen:
                queue.append((next_node, depth + 1, edge))
    return sorted(seen.values(), key=lambda item: (-item["score"], item["type"], item["label"]))[:max_items]


def context_packet(store: GraphStore, task: str, max_depth: int = 2, max_items: int = 20) -> dict:
    candidates = [item for item in store.search(task, max(50, max_items * 3)) if item["type"] in SEED_PRIORITY]
    candidates.sort(key=lambda item: (SEED_PRIORITY[item["type"]], item.get("lexical_rank", 0.0), item["label"]))
    record_seeds = [item for item in candidates if item["type"] in {"Decision", "Constraint", "Architecture", "Incident"}]
    seeds = (record_seeds or candidates)[: min(max_items, 10)]
    items = traverse(store, seeds, max_depth=max_depth, max_items=max_items)
    governing = [item for item in items if item["type"] in {"Decision", "Constraint"} and item.get("data", {}).get("status") in {"accepted", "implemented"}]
    files = [item for item in items if item["type"] == "File"]
    warnings: list[str] = []
    if not seeds:
        warnings.append("No lexical evidence matched the task.")
    if not governing:
        warnings.append("No accepted decision or constraint was found for this task.")
    return {
        "task": task,
        "governing_records": governing,
        "files": files,
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
