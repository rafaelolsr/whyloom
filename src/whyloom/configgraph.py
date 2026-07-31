from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .codegraph import source_hash
from .models import Diagnostic, GraphEdge, GraphNode

MAX_CONFIG_BYTES = 2_000_000
MAX_CONFIG_KEYS = 5_000
MAX_CONFIG_REFERENCE_TARGETS = 5
GENERIC_CONFIG_KEYS = {
    "allowedhosts",
    "description",
    "enabled",
    "environment",
    "identifier",
    "location",
    "metadata",
    "name",
    "properties",
    "resourcegroup",
    "settings",
    "type",
    "value",
    "version",
}


def _flatten(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    flattened: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            child = f"{prefix}.{key}" if prefix else str(key)
            flattened.append((child, "mapping"))
            flattened.extend(_flatten(value[key], child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            child = f"{prefix}[{index}]"
            flattened.append((child, "sequence-item"))
            flattened.extend(_flatten(item, child))
    return flattened


def extract_config(path: Path, root: Path) -> tuple[list[GraphNode], list[GraphEdge], list[Diagnostic]]:
    rel = path.relative_to(root).as_posix()
    digest = source_hash(path)
    file_id = f"file:{rel}"
    nodes = [
        GraphNode(
            id=file_id,
            type="File",
            label=rel,
            path=rel,
            source_path=rel,
            source_hash=digest,
            data={"language": "json" if path.suffix.casefold() == ".json" else "yaml", "configuration": True},
        )
    ]
    edges: list[GraphEdge] = []
    diagnostics: list[Diagnostic] = []
    if path.stat().st_size > MAX_CONFIG_BYTES:
        diagnostics.append(
            Diagnostic(code="CFG002", severity="warning", message="configuration exceeds the safe structural extraction limit", path=rel)
        )
        return nodes, edges, diagnostics
    try:
        text = path.read_text(encoding="utf-8")
        parsed = json.loads(text) if path.suffix.casefold() == ".json" else yaml.safe_load(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, yaml.YAMLError) as exc:
        diagnostics.append(Diagnostic(code="CFG001", severity="warning", message=str(exc), path=rel))
        return nodes, edges, diagnostics
    if not isinstance(parsed, (dict, list)):
        return nodes, edges, diagnostics
    flattened = _flatten(parsed)
    if len(flattened) > MAX_CONFIG_KEYS:
        diagnostics.append(
            Diagnostic(code="CFG003", severity="warning", message="configuration keys were truncated", path=rel)
        )
        flattened = flattened[:MAX_CONFIG_KEYS]
    for key_path, value_type in flattened:
        key_id = f"config:{rel}:{key_path}"
        nodes.append(
            GraphNode(
                id=key_id,
                type="ConfigKey",
                label=key_path,
                path=rel,
                source_path=rel,
                source_hash=digest,
                data={"value_type": value_type},
            )
        )
        edges.append(
            GraphEdge(
                source=file_id,
                target=key_id,
                type="CONFIGURES",
                origin="structured-config",
                provenance="EXTRACTED",
                evidence=rel,
                source_path=rel,
                source_hash=digest,
            )
        )
    return nodes, edges, diagnostics


def _normalized_key(value: str) -> str:
    return "".join(char for char in value.casefold() if char.isalnum())


def resolve_config_references(nodes: list[GraphNode], digest: str) -> list[GraphEdge]:
    config_keys: dict[str, list[GraphNode]] = {}
    for node in nodes:
        if node.type != "ConfigKey":
            continue
        leaf = node.label.rsplit(".", 1)[-1].split("[", 1)[0]
        normalized = _normalized_key(leaf)
        if len(normalized) >= 10 and normalized not in GENERIC_CONFIG_KEYS:
            config_keys.setdefault(normalized, []).append(node)
    edges: list[GraphEdge] = []
    seen: set[tuple[str, str]] = set()
    for node in nodes:
        if node.type != "Symbol":
            continue
        references = node.data.get("references", [])
        names = {item["target"].rsplit(".", 1)[-1] for item in references}
        for name in names:
            matches = config_keys.get(_normalized_key(name), [])
            if len(matches) > MAX_CONFIG_REFERENCE_TARGETS:
                continue
            for config_node in matches:
                key = (node.id, config_node.id)
                if key in seen:
                    continue
                seen.add(key)
                edges.append(
                    GraphEdge(
                        source=node.id,
                        target=config_node.id,
                        type="REFERENCES",
                        origin="config-name-resolver",
                        provenance="INFERRED",
                        evidence=f"shared configuration identifier: {name}",
                        confidence=0.65,
                        source_path="@project-relations",
                        source_hash=digest,
                    )
                )
    return edges
