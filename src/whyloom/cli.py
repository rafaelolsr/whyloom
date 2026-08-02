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
    if "task" in output:
        typer.echo(f"Task: {output['task']}")
    if "target" in output:
        typer.echo(f"Target: {output['target']}")
    typer.echo(json.dumps(output, indent=2, default=str))


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
        payload = explain_target(store, target, config["max_depth"], config["max_items"])
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
    task_summary: str = typer.Option(..., "--task-summary", help="Concise summary of completed work."),
    diff_file: Path | None = typer.Option(None, "--diff-file", exists=True, dir_okay=False),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    diff_text = diff_file.read_text(encoding="utf-8") if diff_file else None
    emit(reflect_project(resolved, task_summary, diff_text, config), as_json)


if __name__ == "__main__":
    app()
