from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import uuid
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import __version__

SKILL_NAMES = ("whyloom", "whyloom-bootstrap")
MARKER_NAME = ".whyloom-managed.json"


class AssistantPlatform(StrEnum):
    AUTO = "auto"
    AGENTS = "agents"
    CLAUDE = "claude"
    CODEX = "codex"
    COPILOT = "copilot"


def bundled_skills_root() -> Path:
    installed = Path(sys.prefix) / "share" / "whyloom" / "skills"
    if all((installed / name / "SKILL.md").is_file() for name in SKILL_NAMES):
        return installed
    checkout = Path(__file__).resolve().parents[2] / "skills"
    if all((checkout / name / "SKILL.md").is_file() for name in SKILL_NAMES):
        return checkout
    raise FileNotFoundError("bundled Whyloom skills are missing; reinstall the whyloom package")


def _platform_destination(
    platform: AssistantPlatform,
    *,
    project: bool,
    root: Path,
    home: Path,
    environment: dict[str, str],
) -> Path:
    if project:
        relative = {
            AssistantPlatform.AGENTS: ".agents/skills",
            AssistantPlatform.CLAUDE: ".claude/skills",
            AssistantPlatform.CODEX: ".agents/skills",
            AssistantPlatform.COPILOT: ".github/skills",
        }[platform]
        return root / relative
    if platform is AssistantPlatform.COPILOT:
        copilot_home = Path(environment.get("COPILOT_HOME", home / ".copilot")).expanduser()
        return copilot_home / "skills"
    relative = {
        AssistantPlatform.AGENTS: ".agents/skills",
        AssistantPlatform.CLAUDE: ".claude/skills",
        AssistantPlatform.CODEX: ".codex/skills",
    }[platform]
    return home / relative


def resolve_destinations(
    platform: AssistantPlatform,
    *,
    project: bool,
    root: Path,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> list[tuple[AssistantPlatform, Path]]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"project root does not exist or is not a directory: {root}")
    home = (home or Path.home()).resolve()
    environment = environment or dict(os.environ)
    if platform is not AssistantPlatform.AUTO:
        return [(platform, _platform_destination(platform, project=project, root=root, home=home, environment=environment))]
    if project:
        return [
            (
                AssistantPlatform.AGENTS,
                _platform_destination(AssistantPlatform.AGENTS, project=True, root=root, home=home, environment=environment),
            )
        ]

    detected: list[AssistantPlatform] = []
    checks = {
        AssistantPlatform.CODEX: home / ".codex",
        AssistantPlatform.COPILOT: Path(environment.get("COPILOT_HOME", home / ".copilot")).expanduser(),
        AssistantPlatform.CLAUDE: home / ".claude",
    }
    for candidate, path in checks.items():
        if path.is_dir():
            detected.append(candidate)
    if not detected:
        detected.append(AssistantPlatform.AGENTS)
    return [
        (
            candidate,
            _platform_destination(candidate, project=False, root=root, home=home, environment=environment),
        )
        for candidate in detected
    ]


def _files_digest(root: Path) -> dict[str, str]:
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == MARKER_NAME:
            continue
        if path.is_symlink():
            raise ValueError(f"skill resources must not contain symlinks: {path}")
        digests[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digests


def _marker(skill: str, files: dict[str, str]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "owner": "whyloom",
        "skill": skill,
        "package_version": __version__,
        "files": files,
    }


def _read_marker(destination: Path, skill: str) -> dict[str, Any] | None:
    path = destination / MARKER_NAME
    if not path.is_file():
        return None
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid Whyloom ownership marker: {path}") from exc
    if marker.get("owner") != "whyloom" or marker.get("skill") != skill:
        raise ValueError(f"destination is not owned by Whyloom: {destination}")
    return marker


def _install_one(source: Path, destination: Path, skill: str) -> str:
    if destination.is_symlink():
        raise ValueError(f"refusing to replace a symlinked skill directory: {destination}")
    files = _files_digest(source)
    marker = _marker(skill, files)
    if destination.exists():
        existing = _read_marker(destination, skill)
        if existing is None:
            raise ValueError(f"refusing to overwrite unowned skill directory: {destination}")
        if existing.get("files") == files and existing.get("package_version") == __version__:
            return "unchanged"

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.parent / f".{skill}.tmp-{uuid.uuid4().hex}"
    backup = destination.parent / f".{skill}.backup-{uuid.uuid4().hex}"
    shutil.copytree(source, temporary)
    (temporary / MARKER_NAME).write_text(json.dumps(marker, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    action = "installed"
    try:
        if destination.exists():
            destination.replace(backup)
            action = "updated"
        temporary.replace(destination)
    except Exception:
        if backup.exists() and not destination.exists():
            backup.replace(destination)
        raise
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
        if backup.exists():
            shutil.rmtree(backup)
    return action


def install_skills(
    platform: AssistantPlatform,
    *,
    project: bool,
    root: Path,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
    source_root: Path | None = None,
) -> dict[str, Any]:
    source_root = source_root or bundled_skills_root()
    destinations = resolve_destinations(platform, project=project, root=root, home=home, environment=environment)
    results: list[dict[str, str]] = []
    for resolved_platform, base in destinations:
        for skill in SKILL_NAMES:
            source = source_root / skill
            if not (source / "SKILL.md").is_file():
                raise FileNotFoundError(f"bundled skill is incomplete: {source}")
            destination = base / skill
            action = _install_one(source, destination, skill)
            results.append(
                {
                    "platform": resolved_platform.value,
                    "skill": skill,
                    "destination": str(destination),
                    "action": action,
                }
            )
    return {"operation": "install", "project": project, "results": results}


def uninstall_skills(
    platform: AssistantPlatform,
    *,
    project: bool,
    root: Path,
    home: Path | None = None,
    environment: dict[str, str] | None = None,
) -> dict[str, Any]:
    destinations = resolve_destinations(platform, project=project, root=root, home=home, environment=environment)
    results: list[dict[str, str]] = []
    for resolved_platform, base in destinations:
        for skill in SKILL_NAMES:
            destination = base / skill
            action = "absent"
            if destination.exists():
                if destination.is_symlink():
                    raise ValueError(f"refusing to remove a symlinked skill directory: {destination}")
                if _read_marker(destination, skill) is None:
                    raise ValueError(f"refusing to remove unowned skill directory: {destination}")
                shutil.rmtree(destination)
                action = "removed"
            results.append(
                {
                    "platform": resolved_platform.value,
                    "skill": skill,
                    "destination": str(destination),
                    "action": action,
                }
            )
    return {"operation": "uninstall", "project": project, "results": results}
