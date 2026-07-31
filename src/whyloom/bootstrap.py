from __future__ import annotations

import hashlib
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
from .operations import GLOSSARY, OVERVIEW, init_project, validate_project
from .path_policy import is_ignored_directory
from .records import discover_records

MANIFEST_VERSION = 2
REQUEST_VERSION = 1
REQUEST_RELATIVE_PATH = ".whyloom/cache/bootstrap/request.json"
MAX_FILE_BYTES = 1_000_000
EXCERPT_LIMIT = 240
MAX_SCANNED_FILES = 20_000
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
    if path.suffix.casefold() in {".py", ".js", ".ts", ".go", ".rs", ".java"}:
        kinds.add("source")
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
    if kind == "source":
        return "file", "Source implementation evidence; use the structural graph to inspect symbols and relationships."
    return "file", f"Repository evidence in {path.name}."


def _walk_evidence(root: Path, max_evidence: int) -> tuple[list[BootstrapEvidence], bool]:
    candidates: dict[str, list[tuple[str, str, str]]] = {}
    paths: list[Path] = []
    scan_truncated = False
    for current, directories, files in os.walk(root, followlinks=False):
        directories[:] = sorted(directory for directory in directories if not is_ignored_directory(directory))
        for name in sorted(files):
            paths.append(Path(current) / name)
            if len(paths) >= MAX_SCANNED_FILES:
                scan_truncated = True
                break
        if scan_truncated:
            break
    for path in paths:
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        kinds = _classify(path, relative)
        text = _safe_text(path) if kinds or path.suffix.casefold() in {".py", ".js", ".ts", ".go", ".rs", ".java"} else None
        for kind in sorted(kinds):
            locator, summary = _file_summary(kind, path, text)
            candidates.setdefault(kind, []).append((relative, locator, summary))
        if text and path.suffix.casefold() in {".py", ".js", ".ts", ".go", ".rs", ".java"}:
            for line_number, line in enumerate(text.splitlines(), start=1):
                match = COMMENT_PATTERN.match(line)
                if not match or not RATIONALE_PATTERN.search(match.group(1)):
                    continue
                candidates.setdefault("rationale-comment", []).append(
                    (relative, f"line:{line_number}", _one_line(match.group(1)))
                )
    selected: list[tuple[str, str, str, str]] = []
    non_empty = sorted(candidates)
    quota = max(1, max_evidence // max(1, len(non_empty)))
    offsets: dict[str, int] = {}
    for kind in non_empty:
        items = candidates[kind]
        take = min(quota, len(items), max_evidence - len(selected))
        selected.extend((kind, *item) for item in items[:take])
        offsets[kind] = take
    while len(selected) < max_evidence:
        progressed = False
        for kind in non_empty:
            offset = offsets[kind]
            if offset >= len(candidates[kind]):
                continue
            selected.append((kind, *candidates[kind][offset]))
            offsets[kind] += 1
            progressed = True
            if len(selected) >= max_evidence:
                break
        if not progressed:
            break
    evidence = [
        BootstrapEvidence(f"EVD-{index:04d}", kind, source, locator, summary)
        for index, (kind, source, locator, summary) in enumerate(selected, start=1)
    ]
    total_candidates = sum(len(items) for items in candidates.values())
    return evidence, scan_truncated or total_candidates > len(evidence)


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


def _render_report(evidence: list[BootstrapEvidence], truncated: bool, structural: dict[str, Any] | None = None) -> str:
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
    if structural:
        structural_coverage = structural.get("coverage", {})
        lines.extend(
            [
                "",
                "## Structural coverage",
                "",
                f"- Indexed files assigned to communities: {structural_coverage.get('files_assigned', 0)}/{structural_coverage.get('files_total', 0)}",
                f"- Communities: {structural_coverage.get('communities_total', 0)}",
                f"- Communities with linked records: {structural_coverage.get('communities_with_records', 0)}",
                f"- Communities missing rationale: {structural_coverage.get('communities_missing_rationale', 0)}",
                f"- Cross-community relationships retained: {len(structural.get('cross_community_relationships', []))}",
            ]
        )
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
            "Installed Whyloom skills should inspect this evidence, compare it with the code graph, and create reviewable records when onboarding is pending.",
            "",
        ]
    )
    return "\n".join(lines)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _request_path(root: Path) -> Path:
    return resolve_repository_path(root, REQUEST_RELATIVE_PATH)


def _read_request(root: Path) -> dict[str, Any] | None:
    path = _request_path(root)
    if not path.exists():
        return None
    try:
        request = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid onboarding request: {path.relative_to(root)}") from exc
    if not isinstance(request, dict) or request.get("request_version") != REQUEST_VERSION:
        raise ValueError(f"unsupported onboarding request: {path.relative_to(root)}")
    if request.get("status") not in {"pending", "completed"}:
        raise ValueError(f"invalid onboarding status in {path.relative_to(root)}")
    return request


def onboarding_status(root: Path) -> dict[str, Any]:
    root = root.resolve()
    try:
        request = _read_request(root)
    except ValueError as exc:
        return {"status": "invalid", "request": REQUEST_RELATIVE_PATH, "error": str(exc)}
    if request is None:
        return {"status": "not_started", "request": REQUEST_RELATIVE_PATH}
    return {
        "status": request["status"],
        "request": REQUEST_RELATIVE_PATH,
        "workflow": request.get("workflow", "whyloom-bootstrap"),
        "evidence_manifest": request.get("evidence_manifest"),
        "completion": request.get("completion"),
    }


def _canonical_memory_changed(root: Path, records_count: int) -> bool:
    overview = root / ".whyloom" / "overview.md"
    glossary = root / ".whyloom" / "glossary.md"
    overview_changed = overview.is_file() and overview.read_text(encoding="utf-8") != OVERVIEW
    glossary_changed = glossary.is_file() and glossary.read_text(encoding="utf-8") != GLOSSARY
    return records_count > 0 or overview_changed or glossary_changed


def bootstrap_project(root: Path, config: dict[str, Any], history_limit: int = 50, max_evidence: int = 500) -> dict[str, Any]:
    if history_limit < 0 or history_limit > 500:
        raise ValueError("history_limit must be between 0 and 500")
    if max_evidence < 1 or max_evidence > 5_000:
        raise ValueError("max_evidence must be between 1 and 5000")
    root = root.resolve()
    index_result = index_project(root, config)
    if not index_result["indexed"]:
        return {"bootstrapped": False, "index": index_result}

    file_budget = max(1, max_evidence - min(history_limit, max_evidence // 4))
    evidence, scan_truncated = _walk_evidence(root, file_budget)
    remaining = max_evidence - len(evidence)
    evidence.extend(_git_evidence(root, history_limit, len(evidence) + 1, remaining))
    truncated = len(evidence) >= max_evidence or scan_truncated
    counts = Counter(item.kind for item in evidence)
    generated_dir = resolve_repository_path(root, ".whyloom/cache/bootstrap")
    manifest_path = generated_dir / "evidence.json"
    report_path = generated_dir / "report.md"
    coverage_path = root / index_result.get("coverage_manifest", "")
    structural = json.loads(coverage_path.read_text(encoding="utf-8")) if coverage_path.is_file() else None
    payload = {
        "manifest_version": MANIFEST_VERSION,
        "authoritative": False,
        "evidence": [asdict(item) for item in evidence],
        "coverage": dict(sorted(counts.items())),
        "structural_coverage": structural,
        "investigation_areas": _investigation_areas(counts),
        "truncated": truncated,
    }
    _atomic_write(manifest_path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
    _atomic_write(report_path, _render_report(evidence, truncated, structural))
    return {
        "bootstrapped": True,
        "index": index_result,
        "evidence_count": len(evidence),
        "coverage": payload["coverage"],
        "truncated": truncated,
        "manifest": manifest_path.relative_to(root).as_posix(),
        "report": report_path.relative_to(root).as_posix(),
        "canonical_records_changed": False,
        "next_action": "Repository evidence is ready for reviewable agent interpretation.",
    }


def onboard_project(
    root: Path,
    config: dict[str, Any],
    history_limit: int = 50,
    max_evidence: int = 500,
    *,
    force: bool = False,
) -> dict[str, Any]:
    root = root.resolve()
    initialized = init_project(root)
    bootstrap = bootstrap_project(root, config, history_limit, max_evidence)
    if not bootstrap["bootstrapped"]:
        return {"onboarded": False, "initialized": initialized, "bootstrap": bootstrap}

    manifest_path = root / bootstrap["manifest"]
    evidence_digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    existing = _read_request(root)
    if existing and not force and existing.get("evidence_sha256") == evidence_digest:
        action = "unchanged"
        request = existing
    else:
        request = {
            "request_version": REQUEST_VERSION,
            "status": "pending",
            "workflow": "whyloom-bootstrap",
            "evidence_manifest": bootstrap["manifest"],
            "report": bootstrap["report"],
            "evidence_sha256": evidence_digest,
            "canonical_records_changed": False,
            "agent_actions": [
                "Inspect every significant structural community and the bounded evidence.",
                "Trace high-signal cross-community workflows and record uncovered areas.",
                "Create only evidence-backed proposed Whyloom records.",
                "Record confidence, citations, and open questions.",
                "Run Whyloom validation and complete onboarding.",
            ],
        }
        _atomic_write(_request_path(root), json.dumps(request, indent=2, sort_keys=True) + "\n")
        action = "created" if existing is None else "refreshed"
    return {
        "onboarded": True,
        "initialized": initialized,
        "bootstrap": bootstrap,
        "onboarding": {
            "status": request["status"],
            "request": REQUEST_RELATIVE_PATH,
            "action": action,
        },
        "next_action": "Continue in the coding agent; an installed Whyloom skill should complete the pending onboarding request.",
    }


def complete_onboarding(root: Path, config: dict[str, Any], summary: str) -> dict[str, Any]:
    root = root.resolve()
    summary = " ".join(summary.split())
    if not summary:
        raise ValueError("completion summary must not be empty")
    request = _read_request(root)
    if request is None:
        raise ValueError("no onboarding request exists; run whyloom onboard first")
    if request["status"] == "completed":
        return {"completed": True, "action": "unchanged", "onboarding": onboarding_status(root)}

    validation = validate_project(root, config)
    if not validation["valid"]:
        raise ValueError("Whyloom records are invalid; run whyloom validate and resolve errors before completing onboarding")
    records, _ = discover_records(root, config["records_dir"])
    if not _canonical_memory_changed(root, len(records)):
        raise ValueError("onboarding produced no project memory; update the overview, glossary, or proposed records first")

    request["status"] = "completed"
    request["canonical_records_changed"] = True
    request["completion"] = {
        "summary": summary,
        "records": len(records),
        "requires_human_review": any(record.status.value == "proposed" for record in records),
    }
    _atomic_write(_request_path(root), json.dumps(request, indent=2, sort_keys=True) + "\n")
    index = index_project(root, config)
    return {
        "completed": True,
        "action": "completed",
        "onboarding": onboarding_status(root),
        "validation": validation,
        "index": index,
    }
