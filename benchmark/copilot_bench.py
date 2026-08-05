#!/usr/bin/env python3
"""Benchmark Whyloom's effect on GitHub Copilot CLL, from Copilot's own local log.

Copilot CLI records every session in ~/.copilot/session-store.db: the tool
commands it ran (forge_trajectory_events), per-call token usage and latency
(assistant_usage_events), and the prompt (turns). This reads that database — no
Langfuse, no screenshots, no estimation — and compares two runs of the same
question: one WITH Whyloom available and one WITHOUT.

Mark the runs by appending a tag to the Copilot prompt, e.g.:
    How does the advisor orchestrator work? [bench-with]
    How does the advisor orchestrator work? [bench-without]

Then:
    python benchmark/copilot_bench.py --with "[bench-with]" --without "[bench-without]"

Reports, per run and as a delta: LLM calls, tool calls, Whyloom calls, grep/read
calls, input/output/cache tokens, and wall-clock duration. Everything is real,
logged data, so the numbers are cite-able to a team.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DB = Path.home() / ".copilot" / "session-store.db"

# Commands that indicate the agent fell back to manual search instead of Whyloom.
_GREP_READ = ("grep", "rg ", "cat ", "head ", "tail ", "find ", "sed ", "awk ")


@dataclass
class RunMetrics:
    session_id: str
    prompt: str
    llm_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    duration_ms: int = 0
    tool_calls: int = 0
    whyloom_calls: int = 0
    grep_read_calls: int = 0
    commands: list[str] = field(default_factory=list)

    @property
    def context_tokens(self) -> int:
        """Tokens the model had to read to answer — the cost that grows when an
        agent reads files instead of querying a graph."""
        return self.input_tokens + self.cache_read_tokens


def _latest_session(con: sqlite3.Connection, tag: str, repo_like: str | None) -> tuple[str, str] | None:
    """The most recent session whose first user message contains the tag."""
    sql = (
        "SELECT t.session_id, t.user_message FROM turns t "
        "JOIN sessions s ON s.id = t.session_id "
        "WHERE t.user_message LIKE ? "
    )
    params: list[str] = [f"%{tag}%"]
    if repo_like:
        sql += "AND s.cwd LIKE ? "
        params.append(f"%{repo_like}%")
    sql += "ORDER BY t.rowid DESC LIMIT 1"
    row = con.execute(sql, params).fetchone()
    return (row[0], row[1]) if row else None


def _metrics(con: sqlite3.Connection, session_id: str, prompt: str) -> RunMetrics:
    m = RunMetrics(session_id=session_id, prompt=prompt.strip())

    usage = con.execute(
        "SELECT COUNT(*), COALESCE(SUM(input_tokens),0), COALESCE(SUM(output_tokens),0), "
        "COALESCE(SUM(cache_read_tokens),0), COALESCE(SUM(duration_ms),0) "
        "FROM assistant_usage_events WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    m.llm_calls, m.input_tokens, m.output_tokens, m.cache_read_tokens, m.duration_ms = usage

    for (command,) in con.execute(
        "SELECT command FROM forge_trajectory_events "
        "WHERE session_id = ? AND event_type = 'command' AND command IS NOT NULL",
        (session_id,),
    ):
        m.tool_calls += 1
        m.commands.append(command)
        if "whyloom" in command:
            m.whyloom_calls += 1
        elif any(tok in command for tok in _GREP_READ):
            m.grep_read_calls += 1
    return m


def _fmt_int(n: int) -> str:
    return f"{n:,}"


def _pct_delta(without: float, with_: float) -> str:
    if without == 0:
        return "n/a"
    change = (with_ - without) / without * 100
    return f"{change:+.0f}%"


def _report(w: RunMetrics, wo: RunMetrics) -> str:
    rows = [
        ("LLM calls", wo.llm_calls, w.llm_calls),
        ("Tool calls", wo.tool_calls, w.tool_calls),
        ("  · whyloom calls", wo.whyloom_calls, w.whyloom_calls),
        ("  · grep/read calls", wo.grep_read_calls, w.grep_read_calls),
        ("Context tokens (read)", wo.context_tokens, w.context_tokens),
        ("Output tokens", wo.output_tokens, w.output_tokens),
        ("Duration (ms)", wo.duration_ms, w.duration_ms),
    ]
    width = max(len(label) for label, _, _ in rows)
    out = [
        "Whyloom Copilot benchmark",
        f"  question: {w.prompt.split('[')[0].strip()!r}",
        "",
        f"  {'metric'.ljust(width)}   {'without':>12}   {'with':>12}   {'delta':>8}",
        f"  {'-' * width}   {'-'*12}   {'-'*12}   {'-'*8}",
    ]
    for label, without, with_ in rows:
        out.append(
            f"  {label.ljust(width)}   {_fmt_int(without):>12}   {_fmt_int(with_):>12}   {_pct_delta(without, with_):>8}"
        )
    saved = wo.context_tokens - w.context_tokens
    if wo.context_tokens:
        out += [
            "",
            f"  → Whyloom read {_pct_delta(wo.context_tokens, w.context_tokens)} the context tokens "
            f"({_fmt_int(saved)} fewer) to answer the same question.",
        ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--with", dest="with_tag", default="[bench-with]", help="prompt tag for the Whyloom-enabled run")
    ap.add_argument("--without", dest="without_tag", default="[bench-without]", help="prompt tag for the baseline run")
    ap.add_argument("--repo", default=None, help="filter sessions whose cwd contains this string")
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help="path to Copilot session-store.db")
    args = ap.parse_args()

    if not args.db.is_file():
        print(f"Copilot session store not found at {args.db}. Is the Copilot CLI installed?")
        return 2

    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        w_ref = _latest_session(con, args.with_tag, args.repo)
        wo_ref = _latest_session(con, args.without_tag, args.repo)
        missing = [t for t, r in ((args.with_tag, w_ref), (args.without_tag, wo_ref)) if r is None]
        if missing:
            print(
                "No Copilot session found for tag(s): " + ", ".join(missing) + ".\n"
                "Run the question in Copilot with the tag appended to the prompt, e.g.\n"
                f"    How does X work? {args.with_tag}\n"
                f"    How does X work? {args.without_tag}"
            )
            return 1
        w = _metrics(con, *w_ref)
        wo = _metrics(con, *wo_ref)
    finally:
        con.close()

    print(_report(w, wo))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
