"""Export the graph as an Obsidian-compatible vault.

Each node becomes a Markdown note; edges become `[[wikilinks]]` grouped by
relationship, so the whole code-and-rationale graph is browsable in Obsidian's
graph view. This is a view over the cache, never a source of truth: records keep
their status, and inferred edges are labeled."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .store import GraphStore

# Human-facing folder per node type.
_FOLDERS = {
    "File": "files",
    "Symbol": "symbols",
    "Decision": "records",
    "Constraint": "records",
    "Architecture": "records",
    "Incident": "records",
    "Rationale": "rationale",
    "Community": "communities",
    "ConfigKey": "config",
}


def _note_name(node: dict) -> str:
    """A filesystem- and wikilink-safe unique note name for a node."""
    label = node.get("label") or node["id"]
    base = re.sub(r"[\\/:*?\"<>|#^\[\]]+", " ", label).strip() or node["id"]
    # Disambiguate with a short id suffix so same-named symbols do not collide.
    suffix = re.sub(r"[^a-zA-Z0-9]+", "", node["id"])[-6:]
    return f"{base} ({suffix})"


def export_obsidian(store: GraphStore, out_dir: Path) -> dict:
    nodes = store.all_nodes()
    edges = store.all_edges()
    names = {node["id"]: _note_name(node) for node in nodes}

    # Group outgoing edges per node for the note body.
    outgoing: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["source"] in names and edge["target"] in names:
            outgoing[edge["source"]].append(edge)

    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for node in nodes:
        folder = out_dir / _FOLDERS.get(node["type"], "other")
        folder.mkdir(parents=True, exist_ok=True)
        note = folder / f"{names[node['id']]}.md"

        status = node.get("data", {}).get("status")
        tags = [f"#{node['type'].lower()}"]
        if status:
            tags.append(f"#{status}")
        lines = [f"# {node.get('label') or node['id']}", "", " ".join(tags), ""]
        if node.get("path"):
            lines += [f"**Path:** `{node['path']}`", ""]
        if status == "proposed":
            lines += ["> [!warning] Proposed — unreviewed rationale, not yet authoritative.", ""]

        links = outgoing.get(node["id"], [])
        if links:
            lines.append("## Relationships")
            lines.append("")
            for edge in sorted(links, key=lambda e: (e["type"], names[e["target"]])):
                mark = "" if edge["provenance"] == "EXTRACTED" else f" _({edge['provenance'].lower()})_"
                lines.append(f"- **{edge['type']}** → [[{names[edge['target']]}]]{mark}")
            lines.append("")
        note.write_text("\n".join(lines), encoding="utf-8")
        written += 1

    # A vault index for orientation.
    counts: dict[str, int] = defaultdict(int)
    for node in nodes:
        counts[node["type"]] += 1
    index = ["# Whyloom vault", "", "A browsable view of the code-and-rationale graph. Not a source of truth.", "", "## Contents", ""]
    index += [f"- {node_type}: {count}" for node_type, count in sorted(counts.items())]
    (out_dir / "README.md").write_text("\n".join(index) + "\n", encoding="utf-8")

    return {"vault": str(out_dir), "notes_written": written, "node_types": dict(sorted(counts.items()))}
