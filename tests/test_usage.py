import json

from whyloom.config import DEFAULT_CONFIG
from whyloom.usage import record_query, usage_report


def test_usage_starts_empty(tmp_path):
    report = usage_report(tmp_path, DEFAULT_CONFIG)
    assert report["total_queries"] == 0
    assert not report["log_present"]


def test_record_and_report_queries(tmp_path):
    (tmp_path / ".whyloom" / "cache").mkdir(parents=True)
    record_query(tmp_path, DEFAULT_CONFIG, "context", "login flow", {"files": 2})
    record_query(tmp_path, DEFAULT_CONFIG, "explain", "src/auth.py", {"found": True})
    record_query(tmp_path, DEFAULT_CONFIG, "context", "token rotation", {"files": 1})

    report = usage_report(tmp_path, DEFAULT_CONFIG)
    assert report["total_queries"] == 3
    assert report["by_command"] == {"context": 2, "explain": 1}
    assert report["recent"][-1]["command"] == "context"
    assert "3 graph queries" in report["summary"]


def test_entries_carry_timestamp_and_actor(tmp_path):
    (tmp_path / ".whyloom" / "cache").mkdir(parents=True)
    record_query(tmp_path, DEFAULT_CONFIG, "context", "x", {"files": 1})
    log = (tmp_path / ".whyloom" / "cache" / "usage.jsonl").read_text().splitlines()
    entry = json.loads(log[0])
    assert entry["at"]  # ISO timestamp present
    assert entry["kind"] in {"human", "process"}


def test_actor_env_var_tags_agent_queries(tmp_path, monkeypatch):
    monkeypatch.setenv("WHYLOOM_ACTOR", "process:claude-code")
    (tmp_path / ".whyloom" / "cache").mkdir(parents=True)
    record_query(tmp_path, DEFAULT_CONFIG, "context", "x", {"files": 1})
    report = usage_report(tmp_path, DEFAULT_CONFIG)
    assert report["agent_queries"] == 1
    assert report["by_kind"] == {"process": 1}


def test_report_scores_freshness_and_hit_rate(tmp_path):
    (tmp_path / ".whyloom" / "cache").mkdir(parents=True)
    record_query(tmp_path, DEFAULT_CONFIG, "explain", "found.py", {"found": True})
    record_query(tmp_path, DEFAULT_CONFIG, "explain", "missing.py", {"found": False})
    report = usage_report(tmp_path, DEFAULT_CONFIG)
    assert report["hit_rate"] == 0.5
    assert report["hits_scored"] == 2
    assert report["last_used_days_ago"] is not None and report["last_used_days_ago"] <= 1
    assert report["used_recently"] is True
    assert report["queries_last_7d"] == 2


def test_logging_never_raises_without_cache_dir(tmp_path):
    # Must be best-effort: no cache dir yet, still must not raise.
    record_query(tmp_path, DEFAULT_CONFIG, "context", "x", {})
    assert usage_report(tmp_path, DEFAULT_CONFIG)["total_queries"] == 1
