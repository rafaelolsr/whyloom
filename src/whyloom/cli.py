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
from .indexer import index_project
from .installer import AssistantPlatform, install_skills, uninstall_skills
from .operations import doctor_project, init_project, reflect_project, validate_project
from .retrieval import compact_context_packet, context_packet, explain_target, find_path, traverse
from .store import GraphStore

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
    except (FileNotFoundError, OSError) as exc:
        fail("IDX001", str(exc), as_json)


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
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Register bundled Whyloom skills with supported AI assistants."""
    try:
        emit(install_skills(platform, project=project_scope, root=root), as_json)
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
    emit(payload, as_json)


@app.command("impact")
def impact_command(
    target: str = typer.Argument(...),
    root: Path | None = typer.Option(None, "--root"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    resolved, config = project(root, as_json)
    with open_existing_store(resolved, config, as_json) as store:
        node = store.node(target) or store.node(f"file:{target}")
        items = traverse(store, [node], config["max_depth"], config["max_items"]) if node else []
    emit(
        {
            "target": target,
            "found": bool(node),
            "affected": {
                "code": [item for item in items if item["type"] in {"File", "Symbol"}],
                "records": [item for item in items if item["type"] in {"Decision", "Constraint", "Architecture", "Incident"}],
            },
            "evidence": items,
        },
        as_json,
    )


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
