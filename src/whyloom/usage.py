"""Local usage log: proof that the graph — not grep — answered queries.

Every read command appends one line to ``.whyloom/cache/usage.jsonl`` recording
which command ran, its target, and a short result summary. ``whyloom usage``
aggregates the log so you can see, concretely, how often an agent reached for the
graph. Purely local and append-only; it never leaves the machine and is safe to
delete (it lives under the disposable cache)."""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

USAGE_RELATIVE = ".whyloom/cache/usage.jsonl"
_MAX_LINES = 5000  # keep the log bounded; oldest entries are trimmed


def _actor() -> str:
    """Who ran this query. A caller (skill, hook, agent) may declare itself via
    ``WHYLOOM_ACTOR`` (convention: ``process:<id>`` / ``human:<id>``). Absent that,
    infer: an interactive terminal is a human; a non-TTY invocation is almost
    always a coding agent or script shelling out, which is exactly the usage we
    want to prove."""
    declared = os.environ.get("WHYLOOM_ACTOR", "").strip()
    if declared:
        return declared[:80]
    return "human:tty" if sys.stdout.isatty() else "process:agent"


def _kind(actor: str) -> str:
    return "human" if actor.startswith("human:") else "process"


def record_query(root: Path, config: dict, command: str, target: str, summary: dict) -> None:
    """Append one usage entry. Best-effort: logging must never break a query."""
    try:
        path = root / config.get("database", ".whyloom/cache/graph.sqlite")
        log_path = path.parent / "usage.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        actor = _actor()
        entry = {
            "command": command,
            "target": target[:120],
            "at": datetime.now(UTC).isoformat(),
            "actor": actor,
            "kind": _kind(actor),
            **summary,
        }
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


def _parse_at(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _is_hit(entry: dict) -> bool | None:
    """Did this query land? A record/target/path lookup reports ``found``; a
    context/impact lookup lands when it returned any file or edge. ``None`` means
    the command has no natural hit/miss (nothing to score)."""
    if "found" in entry:
        return bool(entry["found"])
    if "files" in entry or "records" in entry:
        return bool(entry.get("files") or entry.get("records"))
    counts = entry.get("counts")
    if isinstance(counts, dict):
        return any(counts.values())
    return None


def usage_report(root: Path, config: dict, recent: int = 10) -> dict:
    """Summarize graph usage as an *adoption* signal: is an agent reaching for the
    graph, how recently, and are its queries landing? Answers the operator's real
    question — "is this being used here, or has it gone dark?" """
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

    now = datetime.now(UTC)
    times = [t for t in (_parse_at(e.get("at")) for e in entries) if t]
    last = max(times) if times else None
    first = min(times) if times else None

    def within(days: int) -> int:
        cutoff = now.timestamp() - days * 86400
        return sum(1 for t in times if t.timestamp() >= cutoff)

    hits = [h for h in (_is_hit(e) for e in entries) if h is not None]
    hit_rate = round(sum(hits) / len(hits), 2) if hits else None
    kinds = Counter(e.get("kind", "unknown") for e in entries)
    agent_queries = kinds.get("process", 0)
    counts = Counter(entry.get("command", "?") for entry in entries)

    last_days = round((now - last).total_seconds() / 86400, 1) if last else None
    used_recently = last_days is not None and last_days <= 7
    verdict = _verdict(entries, agent_queries, last_days, hit_rate)

    return {
        "total_queries": len(entries),
        "by_command": dict(sorted(counts.items())),
        "by_kind": dict(kinds),
        "agent_queries": agent_queries,
        "last_used_at": last.isoformat() if last else None,
        "last_used_days_ago": last_days,
        "first_used_at": first.isoformat() if first else None,
        "queries_last_7d": within(7),
        "queries_last_30d": within(30),
        "hit_rate": hit_rate,
        "hits_scored": len(hits),
        "used_recently": used_recently,
        "recent": entries[-recent:],
        "log_present": True,
        "verdict": verdict,
        "summary": verdict,
    }


def _verdict(entries: list, agent_queries: int, last_days: float | None, hit_rate: float | None) -> str:
    if not entries:
        return "No graph queries recorded yet — no evidence an agent has used the graph here."
    who = f"{agent_queries} of {len(entries)} came from an agent" if agent_queries else "all recorded queries look manual"
    if last_days is None:
        freshness = "timing unknown (log predates timestamps)"
    elif last_days <= 1:
        freshness = "last used within a day"
    elif last_days <= 7:
        freshness = f"last used {last_days:g} days ago"
    else:
        freshness = f"⚠ last used {last_days:g} days ago — usage may have gone dark"
    landing = "" if hit_rate is None else f"; {int(hit_rate * 100)}% of scored queries landed"
    return f"{len(entries)} graph queries ({who}); {freshness}{landing}."
