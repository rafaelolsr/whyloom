import shutil
import subprocess

import pytest

from whyloom.hooks import MANAGED_HOOKS, SENTINEL, install_hooks, uninstall_hooks


def _init_repo(path):
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)


def test_install_and_uninstall_roundtrip(tmp_path):
    _init_repo(tmp_path)
    result = install_hooks(tmp_path)
    assert set(result["installed"]) == set(MANAGED_HOOKS)
    for name in MANAGED_HOOKS:
        hook = tmp_path / ".git" / "hooks" / name
        assert hook.exists()
        assert SENTINEL in hook.read_text()
        assert hook.stat().st_mode & 0o111  # executable

    removed = uninstall_hooks(tmp_path)
    assert set(removed["removed"]) == set(MANAGED_HOOKS)
    for name in MANAGED_HOOKS:
        assert not (tmp_path / ".git" / "hooks" / name).exists()


def test_install_preserves_existing_user_hook(tmp_path):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    user_hook = hooks / "post-commit"
    user_hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

    result = install_hooks(tmp_path)
    assert "post-commit" not in result["installed"]
    assert any(item["hook"] == "post-commit" for item in result["skipped"])
    assert "echo mine" in user_hook.read_text()


def test_uninstall_leaves_user_hook(tmp_path):
    _init_repo(tmp_path)
    hooks = tmp_path / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    user_hook = hooks / "post-commit"
    user_hook.write_text("#!/bin/sh\necho mine\n", encoding="utf-8")

    install_hooks(tmp_path)  # installs the others, skips post-commit
    result = uninstall_hooks(tmp_path)
    assert "post-commit" not in result["removed"]
    assert user_hook.exists()
    assert "echo mine" in user_hook.read_text()


def test_install_without_git_errors(tmp_path):
    result = install_hooks(tmp_path)
    assert result["error"]
    assert not result["installed"]


@pytest.mark.skipif(shutil.which("whyloom") is None, reason="whyloom not on PATH; hook cannot invoke it")
def test_hook_reindexes_on_commit(tmp_path):
    from whyloom.operations import init_project

    _init_repo(tmp_path)
    subprocess.run(["git", "config", "commit.gpgsign", "false"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "d@d"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "d"], cwd=tmp_path, check=True)
    (tmp_path / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    init_project(tmp_path)
    install_hooks(tmp_path)

    graph = tmp_path / ".whyloom" / "cache" / "graph.sqlite"
    assert not graph.exists()
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    # The post-commit hook runs `whyloom index`, building the graph.
    assert graph.exists()
