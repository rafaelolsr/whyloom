"""Local usage log: proof that the graph — not grep — answered queries.

Every read command appends one line to ``.whyloom/cache/usage.jsonl`` recording
which command ran, its target, and a short result summary. ``whyloom usage``
aggregates the log so you can see, concretely, how often an agent reached for the
graph. Purely local and append-only; it never leaves the machine and is safe to
delete (it lives under the disposable cache)."""

from __future__ import annotations

import json
from pathlib import Path

USAGE_RELATIVE = ".whyloom/cache/usage.jsonl"
_MAX_LINES = 5000  # keep the log bounded; oldest entries are trimmed


def record_query(root: Path, config: dict, command: str, target: str, summary: dict) -> None:
    """Append one usage entry. Best-effort: logging must never break a query."""
    try:
        path = root / config.get("database", ".whyloom/cache/graph.sqlite")
        log_path = path.parent / "usage.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"command": command, "target": target[:120], **summary}
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        _trim(log_path)
    except OSError:
        pass


def _trim(log_path: Path) -> None:
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    if len(lines) > _MAX_LINES:
        log_path.write_text("\n".join(lines[-_MAX_LINES:]) + "\n", encoding="utf-8")


def usage_report(root: Path, config: dict, recent: int = 10) -> dict:
    """Summarize graph usage: total queries, per-command counts, and the last
    few. This is the concrete signal that the graph is being used over grep."""
    from collections import Counter

    database = root / config.get("database", ".whyloom/cache/graph.sqlite")
    log_path = database.parent / "usage.jsonl"
    if not log_path.is_file():
        return {"total_queries": 0, "by_command": {}, "recent": [], "log_present": False}

    entries: list[dict] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    counts = Counter(entry.get("command", "?") for entry in entries)
    return {
        "total_queries": len(entries),
        "by_command": dict(sorted(counts.items())),
        "recent": entries[-recent:],
        "log_present": True,
        "summary": (
            f"The graph answered {len(entries)} quer{'y' if len(entries) == 1 else 'ies'} "
            "— each one a lookup the agent did against the graph instead of grep."
        ),
    }
