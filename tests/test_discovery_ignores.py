"""Discovery must skip nested worktrees and not leak SyntaxWarnings — both
surfaced by a real onboard hanging on a large repo with .worktrees/."""

import warnings

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.operations import init_project
from whyloom.path_policy import has_ignored_directory, is_ignored_directory
from whyloom.store import GraphStore


def test_worktrees_directory_is_ignored():
    assert is_ignored_directory(".worktrees")
    assert has_ignored_directory(".worktrees/task-3818770/src/mod.py")


def test_nested_worktree_files_not_indexed(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "app.py").write_text("def a():\n    return 1\n", encoding="utf-8")
    wt = root / ".worktrees" / "task-1" / "src"
    wt.mkdir(parents=True)
    (wt / "dup.py").write_text("def dup():\n    return 2\n", encoding="utf-8")

    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        files = [r["path"] for r in store.connection.execute("SELECT path FROM nodes WHERE type = 'File'")]
    assert "src/app.py" in files
    assert not any(".worktrees" in f for f in files)


def test_indexing_bad_escape_emits_no_syntaxwarning(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    # A string with an invalid escape sequence would raise SyntaxWarning at parse.
    (root / "src" / "bad.py").write_text('def f():\n    return "--out-dir C:\\TEMP"\n', encoding="utf-8")
    init_project(root)
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)  # any leaked SyntaxWarning fails the test
        index_project(root, DEFAULT_CONFIG)
