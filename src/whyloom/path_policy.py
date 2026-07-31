from __future__ import annotations

from pathlib import PurePosixPath

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".cache",
        ".direnv",
        ".git",
        ".import_linter_cache",
        ".mypy_cache",
        ".nox",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".whyloom",
        "__pycache__",
        "__pypackages__",
        "build",
        "dist",
        "node_modules",
        "site-packages",
        "target",
        "vendor",
    }
)


def is_ignored_directory(name: str) -> bool:
    normalized = name.casefold()
    return (
        normalized in IGNORED_DIRECTORY_NAMES
        or normalized.startswith(".venv")
        or normalized == "venv"
        or normalized.startswith("venv-")
        or normalized.startswith("venv_")
    )


def has_ignored_directory(path: str) -> bool:
    parts = PurePosixPath(path.replace("\\", "/")).parts
    return any(is_ignored_directory(part) for part in parts[:-1])
