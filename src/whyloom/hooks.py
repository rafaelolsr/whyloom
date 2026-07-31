"""Install client-side Git hooks that keep the graph fresh after commits.

Git hooks are a purely local mechanism: they live under the repository's hooks
directory and run on the developer's machine, independent of the remote host, so
this works the same against GitHub, GitLab, Bitbucket, or Azure DevOps. For
server-side refresh on push (for example an Azure Pipelines job) use
``azure_pipeline_snippet`` instead — that is a pipeline task, not a Git hook.
"""

from __future__ import annotations

from pathlib import Path

# Hooks that imply source may have changed on disk.
MANAGED_HOOKS = ("post-commit", "post-merge", "post-checkout")
SENTINEL = "# >>> whyloom-managed hook >>>"
SENTINEL_END = "# <<< whyloom-managed hook <<<"
_BODY = """#!/bin/sh
{sentinel}
# Keep the Whyloom graph in sync with the working tree. Safe to remove.
command -v whyloom >/dev/null 2>&1 && whyloom index >/dev/null 2>&1 || true
{sentinel_end}
"""


def _git_hooks_dir(root: Path) -> Path | None:
    """Resolve the hooks directory, handling worktrees where .git is a file
    pointing at the real git dir."""
    git = root / ".git"
    if git.is_dir():
        return git / "hooks"
    if git.is_file():
        # `gitdir: /path/to/real` — worktree or submodule.
        try:
            line = git.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if line.startswith("gitdir:"):
            target = Path(line.split(":", 1)[1].strip())
            if not target.is_absolute():
                target = (root / target).resolve()
            return target / "hooks"
    return None


def _is_whyloom_owned(path: Path) -> bool:
    return path.is_file() and SENTINEL in path.read_text(encoding="utf-8", errors="ignore")


def install_hooks(root: Path) -> dict:
    """Install the managed hooks. Never overwrites a pre-existing hook that
    Whyloom does not own; reports those as skipped so the user can act."""
    root = root.resolve()
    hooks_dir = _git_hooks_dir(root)
    if hooks_dir is None:
        return {"installed": [], "skipped": [], "error": "no Git repository found; hooks require a local .git directory"}
    hooks_dir.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    skipped: list[dict] = []
    content = _BODY.format(sentinel=SENTINEL, sentinel_end=SENTINEL_END)
    for name in MANAGED_HOOKS:
        path = hooks_dir / name
        if path.exists() and not _is_whyloom_owned(path):
            skipped.append({"hook": name, "reason": "an existing non-Whyloom hook is present; not overwritten"})
            continue
        path.write_text(content, encoding="utf-8")
        path.chmod(0o755)
        installed.append(name)
    return {"installed": installed, "skipped": skipped, "hooks_dir": str(hooks_dir)}


def uninstall_hooks(root: Path) -> dict:
    """Remove only hooks Whyloom owns; never touch a user's own hooks."""
    root = root.resolve()
    hooks_dir = _git_hooks_dir(root)
    if hooks_dir is None:
        return {"removed": [], "skipped": [], "error": "no Git repository found"}
    removed: list[str] = []
    skipped: list[dict] = []
    for name in MANAGED_HOOKS:
        path = hooks_dir / name
        if not path.exists():
            continue
        if _is_whyloom_owned(path):
            path.unlink()
            removed.append(name)
        else:
            skipped.append({"hook": name, "reason": "not Whyloom-owned; left in place"})
    return {"removed": removed, "skipped": skipped, "hooks_dir": str(hooks_dir)}


def azure_pipeline_snippet() -> str:
    """A ready-to-paste Azure Pipelines step for server-side graph refresh.

    Git hooks run only on the developer's machine; to rebuild the graph on push
    in Azure DevOps, add this task to azure-pipelines.yml instead."""
    return (
        "# azure-pipelines.yml — rebuild the Whyloom graph on every push\n"
        "- script: |\n"
        "    pip install whyloom\n"
        "    whyloom index --json\n"
        "  displayName: 'Whyloom: refresh code-knowledge graph'\n"
    )
