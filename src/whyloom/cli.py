from __future__ import annotations

import json
from pathlib import Path
from typing import Any, NoReturn

import typer
import yaml
from pydantic import ValidationError

from . import __version__
from .bootstrap import bootstrap_project, complete_onboarding, onboard_project, onboarding_status
from .config import find_root, load_config
from .exporters import export_graphml, export_svg
from .hooks import azure_pipeline_snippet, install_hooks, uninstall_hooks
from .indexer import index_project
from .installer import AssistantPlatform, install_skills, uninstall_skills
from .mapview import build_map_payload, render_map_html
from .obsidian import export_obsidian
from .operations import (
    accept_records,
    doctor_project,
    init_project,
    learnings_report,
    propose_from_rationale,
    reflect_project,
    stale_sources,
    validate_project,
)
from .report import build_report_data, render_report_markdown
from .retrieval import compact_context_packet, context_packet, explain_target, find_path, impact_analysis
from .store import CorruptIndexError, GraphStore
from .usage import record_query, usage_report

app = typer.Typer(no_args_is_help=True, invoke_without_command=True, help="Trusted, graph-backed project memory.")
JSON_SCHEMA_VERSION = 1


def emit(payload: dict[str, Any], as_json: bool) -> None:
    output = {"schema_version": JSON_SCHEMA_VERSION, **payload}
    if as_json:
        typer.echo(json.dumps(output, indent=2, default=str))
        return
    typer.echo(render_human(payload))


def render_human(payload: dict[str, Any]) -> str:
    """Render a command result as concise, scannable text. Falls back to compact
    JSON only for shapes without a dedicated renderer, so `--json` stays the way
    to get the full machine-readable payload."""
    lines = _human_lines(payload)
    return "\n".join(lines) if lines is not None else json.dumps(payload, indent=2, default=str)


def _human_lines(p: dict[str, Any]) -> list[str] | None:  # noqa: C901 - a flat dispatch on result shape
    out: list[str] = []

    # Error result.
    if p.get("ok") is False and "error" in p:
        err = p["error"]
        return [f"✗ {err.get('code', 'ERROR')}: {err.get('message', '')}"]

    # install / uninstall.
    if p.get("operation") in {"install", "uninstall"}:
        verb = "Installed" if p["operation"] == "install" else "Removed"
        for r in p.get("results", []):
            out.append(f"  {_mark(r['action'])} {r['skill']} → {r['destination']}")
        for g in p.get("guidance", []):
            if g.get("action") not in {"skipped", "absent", "not-managed"}:
                out.append(f"  {_mark(g['action'])} guidance → {g.get('file', '')}")
        return [f"{verb} Whyloom skills:", *out] if out else [f"{verb}: nothing to do."]

    # doctor.
    if "checks" in p and "ready" in p:
        out.append("✓ Ready" if p["ready"] else "✗ Not ready")
        for c in p["checks"]:
            out.append(f"  {'✓' if c['ok'] else '✗'} {c['name']}: {c['detail']}")
        return out

    # onboard.
    if "onboarded" in p:
        if not p["onboarded"]:
            return ["✗ Onboarding did not complete."]
        ob = p.get("onboarding", {})
        boot = p.get("bootstrap", {})
        out.append(f"✓ Onboarded — request {ob.get('action', 'ready')} ({ob.get('status', '')}).")
        if boot.get("evidence_count") is not None:
            out.append(f"  collected {boot['evidence_count']} evidence item(s)")
        if p.get("next_action"):
            out.append(f"  next: {p['next_action']}")
        return out

    # index (may also carry an onboarding block — handle before status-only).
    if "indexed" in p and "nodes_written" in p:
        out.append(f"Indexed {len(p.get('changed', []))} changed source(s) in {p.get('elapsed_ms', 0)} ms.")
        out.append(f"  nodes +{p['nodes_written']}  edges +{p['edges_written']}  records {p.get('records', 0)}")
        if p.get("removed"):
            out.append(f"  removed {len(p['removed'])} stale source(s)")
        ob = p.get("onboarding", {})
        if ob.get("status") and ob["status"] != "completed":
            out.append(f"  onboarding: {ob['status']}")
        return out

    # onboarding status / completion (status-only payloads).
    if "onboarding" in p and "onboarded" not in p:
        ob = p["onboarding"]
        return [f"Onboarding status: {ob.get('status', 'unknown')}"]

    # context / compact context.
    if "governing_records" in p and ("files" in p or "symbols" in p):
        if "task" in p:
            out.append(f"Task: {p['task']}")
        gov = p["governing_records"]
        out.append(f"Governing records ({len(gov)}):")
        out += [f"  • {r.get('id', '?')} — {r.get('title') or r.get('label', '')}" for r in gov] or ["  (none accepted)"]
        prop = p.get("proposed_records") or []
        if prop:
            out.append(f"Proposed (unreviewed) ({len(prop)}):")
            out += [f"  • {r.get('id', '?')} — {r.get('title', '')}" for r in prop]
        files = [f if isinstance(f, str) else f.get("path") for f in p.get("files", [])]
        if files:
            out.append("Files: " + ", ".join(f for f in files if f))
        for w in p.get("warnings", []):
            out.append(f"  ⚠ {w}")
        return out

    # explain (found or not — the not-found payload omits governing_records).
    if "found" in p and "target" in p and "hops" not in p and "affected" not in p:
        if not p["found"]:
            warn = "; ".join(p.get("warnings", ["not found"]))
            return [f"✗ {p['target']}: {warn}"]
        return _explain_lines(p)

    # path.
    if "hops" in p:
        if not p["found"]:
            return ["✗ No path: " + "; ".join(p.get("warnings", ["not found"]))]
        out.append(f"Path {p.get('source', '')} → {p.get('target', '')} ({p.get('length', 0)} hop(s)):")
        for h in p["hops"]:
            frm, to = h["from"].split(":")[-1], h["to"].split(":")[-1]
            prov = "" if h.get("provenance") == "EXTRACTED" else f" ({h['provenance'].lower()})"
            out.append(f"  {frm} --{h['type']}{prov}--> {to}")
        return out

    # impact.
    if "affected" in p and "counts" in p:
        c = p["counts"]
        out.append(f"Impact of {p.get('target', '')}: "
                   f"{c.get('records', 0)} record(s), {c.get('symbols', 0)} symbol(s), {c.get('callers', 0)} caller(s)")
        syms = [s["name"] for s in p["affected"].get("symbols", [])][:8]
        if syms:
            out.append("  symbols: " + ", ".join(syms))
        callers = [x["label"] for x in p["affected"].get("downstream_callers", [])]
        if callers:
            out.append("  callers: " + ", ".join(callers))
        return out

    # accept.
    if "accepted" in p and "accepted_count" in p:
        if p["accepted"]:
            out.append(f"Accepted {p['accepted_count']} record(s): " + ", ".join(p["accepted"]))
        for s in p.get("skipped", []):
            out.append(f"  • skipped {s['id']}: {s['reason']}")
        out.append(p.get("next_action", ""))
        return [line for line in out if line]

    # reflect.
    if "proposal" in p and "changed_paths" in p:
        out.append(f"Drafted proposal ({p.get('status', 'proposed')}): {p['proposal']}")
        changed = p.get("changed_paths", [])
        if changed:
            out.append("  changed: " + ", ".join(changed[:6]) + ("…" if len(changed) > 6 else ""))
        out.append("  Fill in the Decision/Rationale sections, then accept (or review in a PR).")
        for w in p.get("warnings", []):
            out.append(f"  ⚠ {w}")
        return out

    # propose.
    if "created" in p and "created_count" in p:
        if not p["created"]:
            return [p.get("next_action", "No new proposals.")]
        out.append(f"Drafted {p['created_count']} proposed record(s):")
        out += [f"  • {c}" for c in p["created"]]
        out.append("Review, refine, and accept before treating as authoritative.")
        return out

    # learnings.
    if "uncovered_count" in p:
        out.append(f"Proposals pending: {p.get('proposal_count', 0)}  ·  Uncovered source files: {p['uncovered_count']}")
        for f in p.get("uncovered", [])[:10]:
            out.append(f"  • {f}")
        if p.get("next_action"):
            out.append(p["next_action"])
        return out

    # usage.
    if "total_queries" in p:
        if not p.get("total_queries"):
            return ["No graph queries recorded yet."]
        out.append(p.get("summary", f"{p['total_queries']} queries."))
        for cmd, n in p.get("by_command", {}).items():
            out.append(f"  {cmd}: {n}")
        return out

    # validate.
    if "valid" in p and "errors" in p:
        if p["valid"]:
            return [f"✓ Valid ({p.get('records', 0)} records)"]
        out.append(f"✗ Invalid ({len(p['errors'])} error(s)):")
        out += [f"  • {e.get('code', '')}: {e.get('message', '')}" for e in p["errors"]]
        return out

    # report (god nodes + suggested questions).
    if "god_nodes" in p and "suggested_questions" in p:
        if p.get("report"):
            out.append(f"Report written to {p['report']}")
        t = p.get("totals", {})
        out.append(f"Graph: {t.get('nodes', 0)} nodes, {t.get('edges', 0)} edges, "
                   f"{t.get('accepted_records', 0)} accepted record(s).")
        out.append("Most-connected entities:")
        out += [f"  • {n['label']} ({n['type']}) — {n['degree']} connections" for n in p["god_nodes"][:8]]
        if p["suggested_questions"]:
            out.append("Suggested questions:")
            out += [f"  {i}. {q}" for i, q in enumerate(p["suggested_questions"][:5], 1)]
        return out

    # single-artifact writers (map, export).
    for key, label in (("map", "Map"), ("graphml", "GraphML"), ("svg", "SVG"), ("vault", "Obsidian vault")):
        if key in p:
            extra = f" ({p['notes_written']} notes)" if "notes_written" in p else ""
            return [f"{label} written to {p[key]}{extra}"]

    return None  # no dedicated renderer → caller falls back to JSON


def _wrap(text: str, width: int = 88, indent: str = "  ") -> list[str]:
    """Wrap record prose to a readable width. Markdown list items (`- ...`) keep
    their own line and a hanging indent so bullets stay legible; paragraphs reflow."""
    import textwrap

    text = text.strip()
    if not text:
        return []
    # Split into blocks on list markers so bullets don't collapse into one line.
    blocks: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith(("- ", "* ")):
            blocks.append(stripped)
        elif stripped and blocks and not blocks[-1].startswith(("- ", "* ")):
            blocks[-1] = f"{blocks[-1]} {stripped}"
        elif stripped:
            blocks.append(stripped)
    lines: list[str] = []
    for block in blocks:
        is_item = block.startswith(("- ", "* "))
        lines += textwrap.wrap(
            " ".join(block.split()),
            width=width,
            initial_indent=indent,
            subsequent_indent=indent + ("  " if is_item else ""),
        )
    return lines


def _explain_lines(p: dict[str, Any]) -> list[str]:
    """Render `explain` as a consistent, scannable brief: what the target is, why
    it exists, what was decided, the trade-offs, what it governs, and the proof —
    each section printed only when the records carry that content."""
    out: list[str] = [f"▸ {p.get('target', '')}"]
    gov = p.get("governing_records", [])
    if not gov:
        out.append("  No governing record — rationale for this target is unrecorded.")
        for gap in p.get("knowledge_gaps", []):
            out.append(f"  ⚠ {gap}")
        return out

    for i, r in enumerate(gov):
        if i:
            out.append("")
        badge = "⚠ agent-authored" if r.get("provenance") == "agent-authored" else "human-authored"
        title = r.get("title") or r.get("label", "")
        out.append(f"  {r.get('id', '?')} · {r.get('status', '?')} · {badge}")
        if title:
            out.append(f"  {title}")
        for heading, key in (("Why it exists", "why"), ("What was decided", "decision"), ("Trade-offs", "consequences")):
            body = _wrap(r.get(key, ""))
            if body:
                out.append(f"    {heading}:")
                out += [f"  {line}" for line in body]
        targets = r.get("targets") or []
        if targets:
            out.append("    Applies to: " + ", ".join(targets[:6]) + ("…" if len(targets) > 6 else ""))
        for q in r.get("open_questions") or []:
            out.append(f"    ? {q}")
        out.append(f"    Proof: {r.get('id', '?')}")

    for w in p.get("warnings", []):
        out.append(f"  ⚠ {w}")
    return out


def _mark(action: str) -> str:
    return {"installed": "+", "updated": "~", "created": "+", "appended": "+", "unchanged": "=", "removed": "-"}.get(action, "•")


def fail(code: str, message: str, as_json: bool, exit_code: int = 2) -> NoReturn:
    emit({"ok": False, "error": {"code": code, "message": message}}, as_json)
    raise typer.Exit(code=exit_code)


def project(root: Path | None, as_json: bool) -> tuple[Path, dict]:
    resolved = find_root(root or Path.cwd())
    if not resolved.is_dir():
        fail("ROOT001", f"repository root does not exist or is not a directory: {resolved}", as_json)
    try:
        return resolved, load_config(resolved)
    except (OSError, ValueError, ValidationError, yaml.YAMLError) as exc:
        fail("CFG001", str(exc), as_json)


def open_existing_store(root: Path, config: dict, as_json: bool) -> GraphStore:
    try:
        return GraphStore(root / config["database"], create=False)
    except CorruptIndexError as exc:
        fail("IDX003", str(exc), as_json)
    except (FileNotFoundError, OSError) as exc:
        fail("IDX001", str(exc), as_json)


def add_staleness_warning(payload: dict, root: Path, config: dict, store: GraphStore) -> dict:
    """Append a warning when the graph no longer matches the working tree, so an
    agent never acts on stale structure without knowing. Bounded and best-effort:
    a failure to check never blocks the answer."""
    try:
        stale = stale_sources(root, config, store)
    except (OSError, ValueError):
        return payload
    if stale:
        sample = ", ".join(stale[:5]) + ("…" if len(stale) > 5 else "")
        payload.setdefault("warnings", []).append(
            f"Index is stale: {len(stale)} source(s) changed since indexing ({sample}). "
            "Run 'whyloom index' for current results."
        )
        payload["stale_sources"] = stale
    return payload


@app.callback()
def main(version: bool = typer.Option(False, "--version", help="Show the installed version.", is_eager=True)) -> None:
    if version:
        typer.echo(__version__)
        raise typer.Exit()


@app.command("init")
def init_command(
    root: Path = typer.Argument(Path("."), help="Repository root."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    try:
        emit(init_project(root), as_json)
    except OSError as exc:
        fail("INIT001", str(exc), as_json)


@app.command("install")
def install_command(
    platform: AssistantPlatform = typer.Option(AssistantPlatform.AUTO, "--platform", case_sensitive=False),
    project_scope: bool = typer.Option(False, "--project", help="Install into the current project."),
    root: Path = typer.Option(Path("."), "--root", help="Project root used by --project."),
    guidance: bool = typer.Option(
        True, "--guidance/--no-guidance", help="Also add a Whyloom pointer to the project's agent-instruction file."
    ),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Register bundled Whyloom skills with supported AI assistants."""
    try:
        emit(install_skills(platform, project=project_scope, root=root, guidance=guidance), as_json)
    except (OSError, ValueError) as exc:
        fail("INSTALL001", str(exc), as_json)


@app.command("uninstall")
def uninstall_command(
    platform: AssistantPlatform = typer.Option(AssistantPlatform.AUTO, "--platform", case_sensitive=False),
    project_scope: bool = typer.Option(False, "--project", help="Remove project-scoped skills."),
    root: Path = typer.Option(Path("."), "--root", help="Project root used by --project."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Remove only skill directories managed by Whyloom."""
    try:
        emit(uninstall_skills(platform, project=project_scope, root=root), as_json)
    except (OSError, ValueError) as exc:
        fail("INSTALL002", str(exc), as_json)


@app.command("index")
def index_command(
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    try:
        payload = index_project(resolved, config)
        payload["onboarding"] = onboarding_status(resolved)
    except (OSError, ValueError) as exc:
        fail("IDX002", str(exc), as_json)
    emit(payload, as_json)
    if not payload["indexed"]:
        raise typer.Exit(code=1)


@app.command("onboard")
def onboard_command(
    root: Path | None = typer.Option(None, "--root"),
    history_limit: int = typer.Option(50, "--history-limit", min=0, max=500),
    max_evidence: int = typer.Option(500, "--max-evidence", min=1, max=5_000),
    complete: bool = typer.Option(False, "--complete", help="Validate and close a pending onboarding request."),
    status: bool = typer.Option(False, "--status", help="Show the current onboarding status without changing it."),
    summary: str | None = typer.Option(None, "--summary", help="Concise completion summary required by --complete."),
    force: bool = typer.Option(False, "--force", help="Refresh an unchanged or completed onboarding request."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Prepare or complete evidence-backed onboarding for an existing repository."""
    resolved, config = project(root, as_json)
    if complete and status:
        fail("ONBOARD001", "--complete and --status cannot be used together", as_json)
    try:
        if status:
            payload = {"onboarding": onboarding_status(resolved)}
        elif complete:
            payload = complete_onboarding(resolved, config, summary or "")
        else:
            payload = onboard_project(resolved, config, history_limit, max_evidence, force=force)
    except (OSError, ValueError) as exc:
        fail("ONBOARD001", str(exc), as_json)
    emit(payload, as_json)
    if payload.get("onboarded") is False:
        raise typer.Exit(code=1)


@app.command("bootstrap")
def bootstrap_command(
    root: Path | None = typer.Option(None, "--root"),
    history_limit: int = typer.Option(50, "--history-limit", min=0, max=500),
    max_evidence: int = typer.Option(500, "--max-evidence", min=1, max=5_000),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Collect bounded repository evidence for proposal-only onboarding."""
    resolved, config = project(root, as_json)
    try:
        payload = bootstrap_project(resolved, config, history_limit, max_evidence)
    except (OSError, ValueError) as exc:
        fail("BOOT001", str(exc), as_json)
    emit(payload, as_json)
    if not payload["bootstrapped"]:
        raise typer.Exit(code=1)


@app.command("context")
def context_command(
    task: str = typer.Argument(...),
    root: Path | None = typer.Option(None, "--root"),
    compact: bool = typer.Option(False, "--compact", help="Return a small agent-ready packet."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        payload = context_packet(store, task, config["max_depth"], config["max_items"])
        payload = add_staleness_warning(payload, resolved, config, store)
    record_query(resolved, config, "context", task, {"files": len(payload.get("files", [])), "records": len(payload.get("governing_records", []))})
    emit(compact_context_packet(payload) if compact else payload, as_json)


@app.command("explain")
def explain_command(
    target: str = typer.Argument(...),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        payload = explain_target(store, target, config["max_depth"], config["max_items"], root=resolved, config=config)
        payload = add_staleness_warning(payload, resolved, config, store)
    record_query(resolved, config, "explain", target, {"found": payload.get("found", False)})
    emit(payload, as_json)


@app.command("path")
def path_command(
    source: str = typer.Argument(..., help="Start entity: a symbol, file, or record id or name."),
    target: str = typer.Argument(..., help="End entity: a symbol, file, or record id or name."),
    max_hops: int = typer.Option(8, "--max-hops", help="Maximum path length to search."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        payload = find_path(store, source, target, max_hops=max_hops)
        payload = add_staleness_warning(payload, resolved, config, store)
    record_query(resolved, config, "path", f"{source} -> {target}", {"found": payload.get("found", False), "hops": payload.get("length")})
    emit(payload, as_json)


hook_app = typer.Typer(help="Manage the client-side Git hook that keeps the graph fresh.")
app.add_typer(hook_app, name="hook")


@hook_app.command("install")
def hook_install_command(
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, _ = project(root, as_json)
    result = install_hooks(resolved)
    if result.get("error"):
        fail("HOOK001", result["error"], as_json)
    emit(result, as_json)


@hook_app.command("uninstall")
def hook_uninstall_command(
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, _ = project(root, as_json)
    result = uninstall_hooks(resolved)
    if result.get("error"):
        fail("HOOK001", result["error"], as_json)
    emit(result, as_json)


@hook_app.command("azure")
def hook_azure_command() -> None:
    """Print an Azure Pipelines step for server-side graph refresh on push."""
    typer.echo(azure_pipeline_snippet())


export_app = typer.Typer(help="Export the graph to external formats.")
app.add_typer(export_app, name="export")


@export_app.command("obsidian")
def export_obsidian_command(
    output: Path = typer.Option(Path(".whyloom/cache/obsidian"), "--output", "-o", help="Vault output directory."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Export the graph as an Obsidian-compatible vault of linked Markdown notes."""
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        out_path = output if output.is_absolute() else resolved / output
        result = export_obsidian(store, out_path)
    if out_path.is_relative_to(resolved):
        result["vault"] = out_path.relative_to(resolved).as_posix()
    emit(result, as_json)


@export_app.command("graphml")
def export_graphml_command(
    output: Path = typer.Option(Path(".whyloom/cache/graph.graphml"), "--output", "-o"),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Export the graph as GraphML for Gephi, yEd, or NetworkX."""
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        document = export_graphml(store)
    out_path = output if output.is_absolute() else resolved / output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    emit({"graphml": out_path.relative_to(resolved).as_posix() if out_path.is_relative_to(resolved) else str(out_path)}, as_json)


@export_app.command("svg")
def export_svg_command(
    output: Path = typer.Option(Path(".whyloom/cache/graph.svg"), "--output", "-o"),
    max_nodes: int = typer.Option(400, "--max-nodes", help="Maximum nodes to draw."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Export a static SVG visualization of the graph."""
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        document = export_svg(store, max_nodes=max_nodes)
    out_path = output if output.is_absolute() else resolved / output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    emit({"svg": out_path.relative_to(resolved).as_posix() if out_path.is_relative_to(resolved) else str(out_path)}, as_json)


@app.command("watch")
def watch_command(
    interval: float = typer.Option(2.0, "--interval", help="Seconds between change scans."),
    root: Path | None = typer.Option(None, "--root"),
) -> None:
    """Re-index automatically as source files change (poll-based; Ctrl-C to stop)."""
    import time

    from .indexer import discover_code_paths

    resolved, config = project(root, False)

    def snapshot() -> dict[str, float]:
        paths, _ = discover_code_paths(resolved, config)
        records = (resolved / config["records_dir"]).rglob("*.md")
        stamps: dict[str, float] = {}
        for path in [*paths, *records]:
            try:
                stamps[str(path)] = path.stat().st_mtime
            except OSError:
                continue
        return stamps

    typer.echo(f"Watching {resolved} (interval {interval}s). Ctrl-C to stop.")
    index_project(resolved, config)
    typer.echo("Indexed. Waiting for changes…")
    previous = snapshot()
    try:
        while True:
            time.sleep(interval)
            current = snapshot()
            if current != previous:
                result = index_project(resolved, config)
                changed = len(result.get("changed", []))
                typer.echo(f"Reindexed: {changed} source(s) changed.")
                previous = current
    except KeyboardInterrupt:
        typer.echo("\nStopped watching.")


@app.command("report")
def report_command(
    output: Path | None = typer.Option(None, "--output", "-o", help="Write GRAPH_REPORT.md here instead of stdout."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Summarize the graph: most-connected entities and suggested starter questions."""
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        data = build_report_data(store)
    if output is not None:
        out_path = output if output.is_absolute() else resolved / output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(render_report_markdown(data), encoding="utf-8")
        data["report"] = out_path.relative_to(resolved).as_posix() if out_path.is_relative_to(resolved) else str(out_path)
    emit(data, as_json)


@app.command("map")
def map_command(
    output: Path = typer.Option(Path(".whyloom/cache/map.html"), "--output", "-o", help="Where to write the HTML map."),
    max_nodes: int = typer.Option(600, "--max-nodes", help="Maximum nodes to draw for readability."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        payload = build_map_payload(store, max_nodes=max_nodes)
    document = render_map_html(payload)
    out_path = output if output.is_absolute() else resolved / output
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    emit(
        {
            "map": out_path.relative_to(resolved).as_posix() if out_path.is_relative_to(resolved) else str(out_path),
            "summary": payload["summary"],
        },
        as_json,
    )


@app.command("impact")
def impact_command(
    target: str = typer.Argument(...),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        payload = impact_analysis(store, target, config["max_depth"], config["max_items"])
        payload = add_staleness_warning(payload, resolved, config, store)
    record_query(resolved, config, "impact", target, payload.get("counts", {}))
    emit(payload, as_json)


@app.command("accept")
def accept_command(
    ids: list[str] = typer.Argument(None, help="Record ids to accept (e.g. DEC-0007). Omit with --all."),
    all_proposed: bool = typer.Option(False, "--all", help="Accept every proposed record in one action."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Flip proposed records to accepted (optional; editing status in a PR also works)."""
    resolved, config = project(root, as_json)
    if not ids and not all_proposed:
        fail("ACCEPT001", "give record ids or use --all", as_json)
    emit(accept_records(resolved, config, ids=ids, all_proposed=all_proposed), as_json)


@app.command("propose")
def propose_command(
    limit: int = typer.Option(50, "--limit", help="Maximum records to propose."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Draft reviewable proposed records from in-code rationale comments (WHY/DECISION/HACK)."""
    resolved, config = project(root, as_json)
    emit(propose_from_rationale(resolved, config, limit=limit), as_json)


@app.command("usage")
def usage_command(
    recent: int = typer.Option(10, "--recent", help="How many recent queries to show."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show how often the graph answered queries — proof it is used over grep."""
    resolved, config = project(root, as_json)
    emit(usage_report(resolved, config, recent=recent), as_json)


@app.command("learnings")
def learnings_command(
    changed_only: bool = typer.Option(False, "--changed", help="Limit gaps to files changed since the last index."),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Show pending proposals and rationale gaps so the capture loop stays reliable."""
    resolved, config = project(root, as_json)
    emit(learnings_report(resolved, config, changed_only=changed_only), as_json)


@app.command("validate")
def validate_command(
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    payload = validate_project(resolved, config)
    emit(payload, as_json)
    if not payload["valid"]:
        raise typer.Exit(code=1)


@app.command("doctor")
def doctor_command(
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    payload = doctor_project(resolved, config)
    emit(payload, as_json)
    if not payload["ready"]:
        raise typer.Exit(code=1)


@app.command("reflect")
def reflect_command(
    summary: str = typer.Argument(None, help="Concise summary of what changed and why."),
    task_summary: str = typer.Option(None, "--task-summary", help="Alias for the summary argument."),
    diff_file: Path | None = typer.Option(None, "--diff-file", exists=True, dir_okay=False),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Draft a proposed record from a task summary and the current diff."""
    text = summary or task_summary
    if not text:
        fail(
            "REFLECT001",
            'reflect needs a summary of what changed. Try: whyloom reflect "add session revocation on password change"',
            as_json,
        )
    resolved, config = project(root, as_json)
    diff_text = diff_file.read_text(encoding="utf-8") if diff_file else None
    emit(reflect_project(resolved, text, diff_text, config), as_json)


if __name__ == "__main__":
    app()
