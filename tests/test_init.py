from whyloom.operations import init_project
from whyloom.records import discover_records


def test_init_is_safe_and_idempotent(tmp_path):
    existing = tmp_path / ".whyloom" / "overview.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep me", encoding="utf-8")
    first = init_project(tmp_path)
    second = init_project(tmp_path)
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert (tmp_path / "whyloom.yaml").exists()
    assert (tmp_path / ".whyloom" / "templates" / "decision.md").exists()
    assert ".whyloom/cache/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert second["skipped"]
    assert first["created"]
    records, diagnostics = discover_records(tmp_path)
    assert records == []
    assert diagnostics == []


def test_init_replaces_legacy_broad_ignore_rule(tmp_path):
    (tmp_path / ".gitignore").write_text(".whyloom/\n", encoding="utf-8")
    init_project(tmp_path)
    assert (tmp_path / ".gitignore").read_text(encoding="utf-8") == ".whyloom/cache/\n"
