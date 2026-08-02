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
    assert "graph answered 3 queries" in report["summary"]


def test_logging_never_raises_without_cache_dir(tmp_path):
    # Must be best-effort: no cache dir yet, still must not raise.
    record_query(tmp_path, DEFAULT_CONFIG, "context", "x", {})
    assert usage_report(tmp_path, DEFAULT_CONFIG)["total_queries"] == 1
