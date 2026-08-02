"""Deterministic graph insight report.

Derives "god nodes" (highest-degree entities), rationale coverage, and suggested
starter questions directly from the cached graph — no LLM. The report orients a
newcomer (or an agent) toward the parts of the system worth understanding first,
and toward the rationale gaps worth capturing."""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import GraphStore


def build_report_data(store: GraphStore, top: int = 10) -> dict:
    nodes = {n["id"]: n for n in store.all_nodes()}
    edges = store.all_edges()

    degree: Counter[str] = Counter()
    for edge in edges:
        if edge["source"] in nodes:
            degree[edge["source"]] += 1
        if edge["target"] in nodes:
            degree[edge["target"]] += 1

    def label(node_id: str) -> str:
        node = nodes.get(node_id)
        return node["label"] if node else node_id

    # God nodes: highest-degree code entities (files/symbols), the hubs.
    god_nodes = [
        {"id": nid, "label": label(nid), "type": nodes[nid]["type"], "degree": deg}
        for nid, deg in degree.most_common()
        if nodes.get(nid, {}).get("type") in {"File", "Symbol"}
    ][:top]

    records = [n for n in nodes.values() if n["type"] in {"Decision", "Constraint"}]
    accepted = [n for n in records if n.get("data", {}).get("status") in {"accepted", "implemented"}]
    proposed = [n for n in records if n.get("data", {}).get("status") == "proposed"]

    # Suggested questions target the hubs and the governance gaps.
    questions: list[str] = []
    for node in god_nodes[:5]:
        questions.append(f'Why does `{node["label"]}` exist, and what governs it?')
    if proposed:
        questions.append(f"Review {len(proposed)} proposed record(s): are they accurate enough to accept?")
    for record in accepted[:3]:
        questions.append(f'What is affected if "{record["label"]}" changes?')

    return {
        "totals": {
            "nodes": len(nodes),
            "edges": len(edges),
            "accepted_records": len(accepted),
            "proposed_records": len(proposed),
        },
        "god_nodes": god_nodes,
        "suggested_questions": questions,
        "node_types": dict(sorted(Counter(n["type"] for n in nodes.values()).items())),
    }


def render_report_markdown(data: dict) -> str:
    t = data["totals"]
    lines = [
        "# Whyloom graph report",
        "",
        "A deterministic snapshot of the code-and-rationale graph. Not a source of truth.",
        "",
        "## Overview",
        "",
        f"- Nodes: {t['nodes']}  ·  Edges: {t['edges']}",
        f"- Accepted records: {t['accepted_records']}  ·  Proposed (unreviewed): {t['proposed_records']}",
        "",
        "## Most-connected entities (god nodes)",
        "",
    ]
    if data["god_nodes"]:
        lines += [f"- **{n['label']}** ({n['type']}) — {n['degree']} connections" for n in data["god_nodes"]]
    else:
        lines.append("- None indexed yet.")
    lines += ["", "## Suggested questions", ""]
    lines += [f"{i}. {q}" for i, q in enumerate(data["suggested_questions"], 1)] or ["- None."]
    lines += ["", "## Node types", ""]
    lines += [f"- {node_type}: {count}" for node_type, count in data["node_types"].items()]
    return "\n".join(lines) + "\n"
