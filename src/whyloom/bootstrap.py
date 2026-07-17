from __future__ import annotations

import json
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import resolve_repository_path
from .indexer import index_project

MANIFEST_VERSION = 1
MAX_FILE_BYTES = 1_000_000
EXCERPT_LIMIT = 240
MAX_SCANNED_FILES = 20_000
SKIP_PARTS = {".git", ".whyloom", ".venv", "build", "dist", "node_modules", "vendor"}
DOC_NAMES = {"readme", "contributing", "architecture", "design", "security", "changelog"}
DEPENDENCY_NAMES = {
    "cargo.toml",
    "composer.json",
    "gemfile",
    "go.mod",
    "package.json",
    "pom.xml",
    "pyproject.toml",
    "requirements.txt",
}
CONFIG_NAMES = {
    "dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "makefile",
    "tox.ini",
    "whyloom.yaml",
}
RATIONALE_PATTERN = re.compile(r"\b(because|decision|intent|must|reason|trade-?off|why|workaround)\b", re.IGNORECASE)
COMMENT_PATTERN = re.compile(r"^\s*(?:#|//|/\*|\*|<!--)\s*(.+?)(?:\s*-->|\s*\*/)?\s*$")


@dataclass(frozen=True)
class BootstrapEvidence:
    id: str
    kind: str
    source: str
    locator: str
    summary: str


def _safe_text(path: Path) -> str | None:
    try:
        if path.is_symlink() or path.stat().st_size > MAX_FILE_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _one_line(value: str, limit: int = EXCERPT_LIMIT) -> str:
    return " ".join(value.split())[:limit]


def _classify(path: Path, relative: str) -> set[str]:
    name = path.name.casefold()
    stem = path.stem.casefold()
    parts = {part.casefold() for part in path.parts}
    kinds: set[str] = set()
    if stem in DOC_NAMES or path.suffix.casefold() in {".md", ".rst"} or "docs" in parts:
        kinds.add("documentation")
    if "test" in parts or "tests" in parts or name.startswith("test_") or name.endswith("_test.py"):
        kinds.add("test")
    if name in DEPENDENCY_NAMES:
        kinds.add("dependency")
    if (
        name in CONFIG_NAMES
        or relative.startswith(".github/workflows/")
        or path.suffix.casefold() in {".tf", ".toml", ".yaml", ".yml"}
    ):
        kinds.add("configuration")
    return kinds


def _file_summary(kind: str, path: Path, text: str | None) -> tuple[str, str]:
    if kind == "documentation" and text:
        headings = [line.lstrip("# ").strip() for line in text.splitlines() if line.startswith("#")]
        if headings:
            return "headings", _one_line("; ".join(headings[:4]))
    if kind == "test":
        return "file", "Test evidence; inspect assertions and fixtures before inferring behavior."
    if kind == "dependency":
        return "file", "Dependency manifest; inspect declared libraries and runtime constraints."
    if kind == "configuration":
        return "file", "Configuration or automation evidence; inspect values before inferring policy."
    return "file", f"Repository evidence in {path.name}."


def _walk_evidence(root: Path, max_evidence: int) -> tuple[list[BootstrapEvidence], bool]:
    evidence: list[BootstrapEvidence] = []
    paths: list[Path] = []
    scan_truncated = False
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(directory for directory in directories if directory not in SKIP_PARTS)
        for name in sorted(files):
            paths.append(Path(current) / name)
            if len(paths) >= MAX_SCANNED_FILES:
                scan_truncated = True
                break
        if scan_truncated:
            break
    for path in paths:
        if len(evidence) >= max_evidence:
            break
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        kinds = _classify(path, relative)
        text = _safe_text(path) if kinds or path.suffix.casefold() in {".py", ".js", ".ts", ".go", ".rs", ".java"} else None
        for kind in sorted(kinds):
            if len(evidence) >= max_evidence:
                break
            locator, summary = _file_summary(kind, path, text)
            evidence.append(BootstrapEvidence(f"EVD-{len(evidence) + 1:04d}", kind, relative, locator, summary))
        if text and path.suffix.casefold() in {".py", ".js", ".ts", ".go", ".rs", ".java"} and len(evidence) < max_evidence:
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = COMMENT_PATTERN.match(line)
                if not match or not RATIONALE_PATTERN.search(match.group(1)):
                    continue
                evidence.append(
                    BootstrapEvidence(
                        f"EVD-{len(evidence) + 1:04d}",
                        "rationale-comment",
                        relative,
                        f"line:{line_number}",
                        _one_line(match.group(1)),
                    )
                )
                if len(evidence) >= max_evidence:
                    break
    return evidence, scan_truncated


def _git_evidence(root: Path, history_limit: int, start: int, remaining: int) -> list[BootstrapEvidence]:
    if history_limit == 0 or remaining == 0:
        return []
    try:
        result = subprocess.run(
            ["git", "log", f"--max-count={min(history_limit, remaining)}", "--format=%H%x09%s"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    evidence: list[BootstrapEvidence] = []
    for offset, line in enumerate(result.stdout.splitlines(), start=start):
        commit, separator, subject = line.partition("\t")
        if not separator:
            continue
        evidence.append(BootstrapEvidence(f"EVD-{offset:04d}", "git-history", f"git:{commit}", "subject", _one_line(subject)))
    return evidence


def _investigation_areas(counts: Counter[str]) -> list[str]:
    areas = ["Map major source directories and their dependency boundaries."]
    if counts["documentation"]:
        areas.append("Compare documented architecture and decisions with the current implementation.")
    else:
        areas.append("Recover architectural intent because no documentation evidence was discovered.")
    if counts["git-history"]:
        areas.append("Inspect high-signal commits for decisions and rejected alternatives.")
    if counts["test"]:
        areas.append("Use tests as behavioral evidence, not as proof of design intent.")
    if counts["rationale-comment"]:
        areas.append("Validate rationale comments against code and history before proposing records.")
    return areas


def _render_report(evidence: list[BootstrapEvidence], truncated: bool) -> str:
    counts = Counter(item.kind for item in evidence)
    lines = [
        "# Whyloom bootstrap report",
        "",
        "Generated evidence is a discovery aid. It is not authoritative project reasoning.",
        "",
        "## Evidence coverage",
        "",
    ]
    if counts:
        lines.extend(f"- {kind}: {counts[kind]}" for kind in sorted(counts))
    else:
        lines.append("- No supported evidence discovered.")
    if truncated:
        lines.append("- Warning: evidence collection reached the configured limit.")
    lines.extend(["", "## Investigation areas", ""])
    lines.extend(f"- {area}" for area in _investigation_areas(counts))
    lines.extend(
        [
            "",
            "## Review boundary",
            "",
            "- Treat every inferred decision, constraint, and architectural claim as proposed.",
            "- Cite evidence identifiers and state confidence on every proposal.",
            "- Record uncertainty as open questions instead of inventing rationale.",
            "- Require human review before changing a proposal to accepted or implemented.",
            "",
            "## Next step",
            "",
            "Run the `whyloom-bootstrap` skill to inspect this evidence, compare it with the code graph, and create reviewable records.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def bootstrap_project(root: Path, config: dict[str, Any], history_limit: int = 50, max_evidence: int = 500) -> dict[str, Any]:
    if history_limit < 0 or history_limit > 500:
        raise ValueError("history_limit must be between 0 and 500")
    if max_evidence < 1 or max_evidence > 5_000:
        raise ValueError("max_evidence must be between 1 and 5000")
    root = root.resolve()
    index_result = index_project(root, config)
    if not index_result["indexed"]:
        return {"bootstrapped": False, "index": index_result}

    evidence, scan_truncated = _walk_evidence(root, max_evidence)
    remaining = max_evidence - len(evidence)
    evidence.extend(_git_evidence(root, history_limit, len(evidence) + 1, remaining))
    truncated = len(evidence) >= max_evidence or scan_truncated
    counts = Counter(item.kind for item in evidence)
    generated_dir = resolve_repository_path(root, ".whyloom/cache/bootstrap")
    manifest_path = generated_dir / "evidence.json"
    report_path = generated_dir / "report.md"
    payload = {
        "manifest_version": MANIFEST_VERSION,
        "authoritative": False,
        "evidence": [asdict(item) for item in evidence],
        "coverage": dict(sorted(counts.items())),
        "investigation_areas": _investigation_areas(counts),
        "truncated": truncated,
    }
    _atomic_write(manifest_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _atomic_write(report_path, _render_report(evidence, truncated))
    return {
        "bootstrapped": True,
        "index": index_result,
        "evidence_count": len(evidence),
        "coverage": payload["coverage"],
        "truncated": truncated,
        "manifest": manifest_path.relative_to(root).as_posix(),
        "report": report_path.relative_to(root).as_posix(),
        "canonical_records_changed": False,
        "next_action": "Run the whyloom-bootstrap skill to create evidence-backed proposals for review.",
    }
