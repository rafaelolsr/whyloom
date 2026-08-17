"""Read-only MCP server over the whyloom graph.

Exposes the deterministic query surface (context, explain, impact, path, flow)
to MCP clients — Claude Desktop, Cursor, Windsurf, VS Code — as a thin
transport over the same functions the CLI uses, returning payloads identical to
``whyloom <command> --json``. Writing is deliberately absent: propose/accept
stay in the CLI and in pull requests, so a connected agent cannot bypass the
human review gate.

The ``mcp`` package is an optional extra (``pip install "whyloom[mcp]"``);
everything that needs it is imported lazily so the query helpers below stay
importable — and testable — without it."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from .cli import JSON_SCHEMA_VERSION, add_staleness_warning
from .config import find_root, load_config
from .retrieval import context_packet, explain_target, find_path, flow_trace, impact_analysis
from .store import CorruptIndexError, GraphStore
from .usage import record_query


def _run(
    root: Path,
    config: dict,
    command: str,
    target: str,
    build: Callable[[GraphStore], dict],
    summary: Callable[[dict], dict],
) -> dict:
    """Open the store, build one query payload, and log usage — the MCP twin of
    the CLI's per-command body. Errors return the contract's error object
    instead of raising, so a client always gets one well-formed result."""
    try:
        store = GraphStore(root / config["database"], create=False)
    except CorruptIndexError as exc:
        return {"schema_version": JSON_SCHEMA_VERSION, "ok": False, "error": {"code": "IDX003", "message": str(exc)}}
    except (FileNotFoundError, OSError) as exc:
        return {"schema_version": JSON_SCHEMA_VERSION, "ok": False, "error": {"code": "IDX001", "message": str(exc)}}
    with store:
        payload = build(store)
        payload = add_staleness_warning(payload, root, config, store)
    record_query(root, config, command, target, summary(payload))
    return {"schema_version": JSON_SCHEMA_VERSION, **payload}


def context_query(root: Path, config: dict, task: str) -> dict:
    return _run(
        root,
        config,
        "context",
        task,
        lambda store: context_packet(store, task, config["max_depth"], config["max_items"]),
        lambda p: {"files": len(p.get("files", [])), "records": len(p.get("governing_records", []))},
    )


def explain_query(root: Path, config: dict, target: str) -> dict:
    return _run(
        root,
        config,
        "explain",
        target,
        lambda store: explain_target(store, target, config["max_depth"], config["max_items"], root=root, config=config),
        lambda p: {"found": p.get("found", False)},
    )


def impact_query(root: Path, config: dict, target: str) -> dict:
    return _run(
        root,
        config,
        "impact",
        target,
        lambda store: impact_analysis(store, target, config["max_depth"], config["max_items"]),
        lambda p: p.get("counts", {}),
    )


def path_query(root: Path, config: dict, source: str, target: str, max_hops: int = 8) -> dict:
    return _run(
        root,
        config,
        "path",
        f"{source} -> {target}",
        lambda store: find_path(store, source, target, max_hops=max_hops),
        lambda p: {"found": p.get("found", False), "hops": p.get("length")},
    )


def flow_query(root: Path, config: dict, target: str, depth: int = 3) -> dict:
    return _run(
        root,
        config,
        "flow",
        target,
        lambda store: flow_trace(store, target, max_depth=depth),
        lambda p: {"found": p.get("found", False)},
    )


def build_server(root: Path | None = None):
    """Build the FastMCP server with one read-only tool per query command.

    Requires the optional ``mcp`` extra; the import lives here so the rest of
    the module works without it."""
    try:  # SDK 2.x renamed FastMCP to MCPServer; the surface we use is identical.
        from mcp.server.mcpserver import MCPServer as _Server
    except ModuleNotFoundError:  # SDK 1.x
        from mcp.server.fastmcp import FastMCP as _Server

    resolved = find_root((root or Path.cwd()).resolve())
    config = load_config(resolved)
    server = _Server(
        "whyloom",
        instructions=(
            "Trusted, graph-backed project memory for this repository. Every answer is "
            "grounded in a deterministic code graph plus human-reviewed decision records; "
            "relationships carry provenance and confidence you can verify. Read-only: to "
            "record new rationale, run `whyloom reflect` from a shell — acceptance stays "
            "with a human."
        ),
    )

    @server.tool()
    def whyloom_context(task: str) -> dict:
        """Task-specific context bundle: the most relevant files, symbols, and the
        accepted decisions/constraints that govern them. Call before planning a change."""
        return context_query(resolved, config, task)

    @server.tool()
    def whyloom_explain(target: str) -> dict:
        """What a file, symbol, or record is and why it exists: governing records,
        related code, and knowledge gaps for the target."""
        return explain_query(resolved, config, target)

    @server.tool()
    def whyloom_impact(target: str) -> dict:
        """What a change to the target affects: real reverse-dependency callers,
        files, symbols, and the records that constrain the change."""
        return impact_query(resolved, config, target)

    @server.tool()
    def whyloom_path(source: str, target: str, max_hops: int = 8) -> dict:
        """Shortest relationship path between two entities (symbols, files, or
        record ids), hop by hop with provenance and confidence."""
        return path_query(resolved, config, source, target, max_hops=max_hops)

    @server.tool()
    def whyloom_flow(target: str, depth: int = 3) -> dict:
        """Ordered execution skeleton from an entry file or symbol — the call
        sequence, each step citing the file and line it resolves to."""
        return flow_query(resolved, config, target, depth=depth)

    return server


def serve(root: Path | None = None) -> None:
    """Run the server over stdio (the transport MCP clients spawn)."""
    # MCP queries are agent traffic; label them unless the caller already did.
    os.environ.setdefault("WHYLOOM_ACTOR", "process:mcp")
    build_server(root).run()
