from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

DEFAULT_INCLUDE_PATTERNS = [
    "**/*.py",
    "**/*.ts",
    "**/*.tsx",
    "**/*.js",
    "**/*.jsx",
    "**/*.mjs",
    "**/*.cjs",
    "**/*.go",
    "**/*.rs",
    "**/*.java",
    "**/*.cs",
    "*.json",
    "*.yaml",
    "*.yml",
    ".github/workflows/*.yaml",
    ".github/workflows/*.yml",
    "config/**/*.json",
    "config/**/*.yaml",
    "config/**/*.yml",
    "configs/**/*.json",
    "configs/**/*.yaml",
    "configs/**/*.yml",
    "deploy/**/*.json",
    "deploy/**/*.yaml",
    "deploy/**/*.yml",
    "deployment/**/*.json",
    "deployment/**/*.yaml",
    "deployment/**/*.yml",
    "infra/**/*.json",
    "infra/**/*.yaml",
    "infra/**/*.yml",
    "infrastructure/**/*.json",
    "infrastructure/**/*.yaml",
    "infrastructure/**/*.yml",
    "templates/**/*.json",
    "templates/**/*.yaml",
    "templates/**/*.yml",
]


class WhyloomConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal[1] = 1
    records_dir: str = ".whyloom"
    database: str = ".whyloom/cache/graph.sqlite"
    include: list[str] = Field(default_factory=lambda: list(DEFAULT_INCLUDE_PATTERNS))
    exclude: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            ".whyloom/cache/**",
            ".venv*/**",
            "venv/**",
            "venv-*/**",
            ".tox/**",
            ".nox/**",
            ".mypy_cache/**",
            ".pytest_cache/**",
            ".ruff_cache/**",
            ".cache/**",
            ".import_linter_cache/**",
            "__pypackages__/**",
            "**/site-packages/**",
            "**/node_modules/**",
            "build/**",
            "dist/**",
        ]
    )
    max_depth: int = Field(default=2, ge=0, le=5)
    max_items: int = Field(default=20, ge=1, le=200)

    @field_validator("records_dir", "database")
    @classmethod
    def repository_relative_path(cls, value: str) -> str:
        normalized = value.replace("\\", "/").strip()
        path = PurePosixPath(normalized)
        if not normalized or path.is_absolute() or ".." in path.parts:
            raise ValueError("must be a non-empty repository-relative path without '..'")
        return path.as_posix()

    @field_validator("include", "exclude")
    @classmethod
    def non_empty_patterns(cls, values: list[str]) -> list[str]:
        if not values or any(not value.strip() for value in values):
            raise ValueError("must contain non-empty glob patterns")
        for value in values:
            path = PurePosixPath(value.replace("\\", "/"))
            if path.is_absolute() or ".." in path.parts:
                raise ValueError("glob patterns must remain repository-relative")
        return values


DEFAULT_CONFIG = WhyloomConfig().model_dump()


def resolve_repository_path(root: Path, relative: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / relative).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"configured path resolves outside repository: {relative}") from exc
    return resolved


def find_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (
            (candidate / "whyloom.yaml").is_file()
            or (candidate / ".whyloom").is_dir()
            or (candidate / "whyloom").is_dir()
        ):
            return candidate
    return current


def load_config(root: Path) -> dict:
    path = root / "whyloom.yaml"
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if loaded is None:
        loaded = {}
    if not isinstance(loaded, dict):
        raise ValueError("whyloom.yaml must contain a YAML mapping")
    config = WhyloomConfig.model_validate({**DEFAULT_CONFIG, **loaded}).model_dump()
    resolve_repository_path(root, config["records_dir"])
    resolve_repository_path(root, config["database"])
    return config
