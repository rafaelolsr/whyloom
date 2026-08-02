"""Static graph exporters: GraphML (Gephi/yEd) and SVG.

Both are deterministic views over the cached graph — no LLM, no network. GraphML
carries node type, path, and status plus edge type/provenance so external tools
can style and analyze the graph. SVG is a self-contained image using the same
seeded force layout as the HTML map, so the picture is reproducible."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape, quoteattr

if TYPE_CHECKING:
    from .store import GraphStore

_TYPE_COLORS = {
    "Decision": "#fbbf24",
    "Constraint": "#f97316",
    "File": "#38bdf8",
    "Symbol": "#5eead4",
    "ConfigKey": "#a78bfa",
    "Community": "#64748b",
    "Rationale": "#94a3b8",
}


def export_graphml(store: GraphStore) -> str:
    """Return a GraphML document (Gephi/yEd/NetworkX compatible)."""
    nodes = store.all_nodes()
    ids = {n["id"] for n in nodes}
    edges = [e for e in store.all_edges() if e["source"] in ids and e["target"] in ids]

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="ntype" for="node" attr.name="type" attr.type="string"/>',
        '  <key id="path" for="node" attr.name="path" attr.type="string"/>',
        '  <key id="status" for="node" attr.name="status" attr.type="string"/>',
        '  <key id="etype" for="edge" attr.name="type" attr.type="string"/>',
        '  <key id="provenance" for="edge" attr.name="provenance" attr.type="string"/>',
        '  <graph edgedefault="directed">',
    ]
    for node in nodes:
        status = node.get("data", {}).get("status") or ""
        lines.append(f"    <node id={quoteattr(node['id'])}>")
        lines.append(f"      <data key=\"label\">{escape(node.get('label') or node['id'])}</data>")
        lines.append(f'      <data key="ntype">{escape(node["type"])}</data>')
        if node.get("path"):
            lines.append(f"      <data key=\"path\">{escape(node['path'])}</data>")
        if status:
            lines.append(f'      <data key="status">{escape(status)}</data>')
        lines.append("    </node>")
    for i, edge in enumerate(edges):
        lines.append(f"    <edge id=\"e{i}\" source={quoteattr(edge['source'])} target={quoteattr(edge['target'])}>")
        lines.append(f'      <data key="etype">{escape(edge["type"])}</data>')
        lines.append(f'      <data key="provenance">{escape(edge["provenance"])}</data>')
        lines.append("    </edge>")
    lines += ["  </graph>", "</graphml>", ""]
    return "\n".join(lines)


def _layout(nodes: list[dict], edges: list[dict], width: int, height: int, iterations: int = 200) -> dict[str, tuple[float, float]]:
    """A small deterministic force-directed layout (seeded LCG, no RNG import)."""
    idx = {n["id"]: i for i, n in enumerate(nodes)}
    seed = 1

    def rnd() -> float:
        nonlocal seed
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        return seed / 0x7FFFFFFF

    pos = [[rnd() * width, rnd() * height] for _ in nodes]
    vel = [[0.0, 0.0] for _ in nodes]
    links = [(idx[e["source"]], idx[e["target"]]) for e in edges if e["source"] in idx and e["target"] in idx]
    for _ in range(iterations):
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                dx, dy = pos[i][0] - pos[j][0], pos[i][1] - pos[j][1]
                dist = math.hypot(dx, dy) or 1.0
                force = 1400.0 / (dist * dist)
                ux, uy = dx / dist, dy / dist
                vel[i][0] += ux * force
                vel[i][1] += uy * force
                vel[j][0] -= ux * force
                vel[j][1] -= uy * force
        for a, b in links:
            dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
            dist = math.hypot(dx, dy) or 1.0
            force = (dist - 90) * 0.02
            ux, uy = dx / dist, dy / dist
            vel[a][0] += ux * force
            vel[a][1] += uy * force
            vel[b][0] -= ux * force
            vel[b][1] -= uy * force
        for i in range(len(nodes)):
            vel[i][0] *= 0.85
            vel[i][1] *= 0.85
            pos[i][0] = min(width - 20, max(20, pos[i][0] + vel[i][0]))
            pos[i][1] = min(height - 20, max(20, pos[i][1] + vel[i][1]))
    return {nodes[i]["id"]: (pos[i][0], pos[i][1]) for i in range(len(nodes))}


def export_svg(store: GraphStore, width: int = 1200, height: int = 800, max_nodes: int = 400) -> str:
    """Return a self-contained SVG of the graph (bounded for readability)."""
    nodes = store.all_nodes()[:max_nodes]
    ids = {n["id"] for n in nodes}
    edges = [e for e in store.all_edges() if e["source"] in ids and e["target"] in ids]
    pos = _layout(nodes, edges, width, height)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" fill="#0b1018"/>',
    ]
    for edge in edges:
        x1, y1 = pos[edge["source"]]
        x2, y2 = pos[edge["target"]]
        dash = ' stroke-dasharray="4,4"' if edge["provenance"] != "EXTRACTED" else ""
        parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="#334155" stroke-width="1"{dash}/>')
    for node in nodes:
        x, y = pos[node["id"]]
        color = _TYPE_COLORS.get(node["type"], "#888888")
        r = 8 if node["type"] in {"Decision", "Constraint", "Community"} else 5
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"/>')
        label = escape((node.get("label") or node["id"])[:30])
        parts.append(f'<text x="{x + r + 2:.1f}" y="{y + 3:.1f}" font-family="sans-serif" font-size="9" fill="#cbd5e1">{label}</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"
