from whyloom.operations import init_project


def test_init_is_safe_and_idempotent(tmp_path):
    existing = tmp_path / "whyloom" / "overview.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("keep me", encoding="utf-8")
    first = init_project(tmp_path)
    second = init_project(tmp_path)
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert (tmp_path / "whyloom.yaml").exists()
    assert (tmp_path / ".whyloom" / "templates" / "decision.md").exists()
    assert ".whyloom/" in (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert second["skipped"]
    assert first["created"]

