import shutil
import subprocess
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.operations import reflect_project, validate_project

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_validation_and_reflection(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    validation = validate_project(root, DEFAULT_CONFIG)
    assert validation["valid"]

    proposal = reflect_project(
        root,
        "Keep token fingerprints server-side",
        "diff --git a/src/sample/auth.py b/src/sample/auth.py\n+++ b/src/sample/auth.py\n",
    )
    path = root / proposal["proposal"]
    assert proposal["status"] == "proposed"
    assert proposal["requires_review"]
    assert "status: proposed" in path.read_text(encoding="utf-8")


def test_validation_fails_for_broken_target(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    record = root / ".whyloom" / "constraints" / "0001-no-token-storage.md"
    record.write_text(record.read_text(encoding="utf-8").replace("src/sample/auth.py", "missing.py"), encoding="utf-8")
    result = validate_project(root, DEFAULT_CONFIG)
    assert not result["valid"]
    assert result["errors"][0]["code"] == "LINK001"


def test_validation_detects_supersession_cycle(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    decision = root / ".whyloom" / "decisions" / "0001-token-storage.md"
    constraint = root / ".whyloom" / "constraints" / "0001-no-token-storage.md"
    decision.write_text(decision.read_text(encoding="utf-8").replace("supersedes: []", "supersedes: [CON-0001]"), encoding="utf-8")
    constraint.write_text(constraint.read_text(encoding="utf-8").replace("supersedes: []", "supersedes: [DEC-0001]"), encoding="utf-8")
    result = validate_project(root, DEFAULT_CONFIG)
    assert not result["valid"]
    assert any(item["code"] == "LIFE002" for item in result["errors"])


def test_reflection_without_git_uses_filesystem_baseline(tmp_path):
    from whyloom.indexer import index_project
    from whyloom.operations import init_project

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("def rotate():\n    return 1\n", encoding="utf-8")
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    # Change the file after indexing so filesystem detection has a delta.
    (root / "src" / "auth.py").write_text("def rotate():\n    return 1\n\ndef revoke():\n    return 2\n", encoding="utf-8")

    result = reflect_project(root, "Add session revocation", config=DEFAULT_CONFIG)
    assert result["baseline"] == "filesystem"
    assert result["changed_paths"] == ["src/auth.py"]
    # The brief reports symbols from the last index, giving the agent structural
    # context for the file that changed (re-index to reflect post-edit symbols).
    assert result["agent_brief"]["changed_symbols"]["src/auth.py"] == ["rotate"]
    assert not any(".whyloom/templates" in p for p in result["changed_paths"])


def test_reflection_proposal_has_agent_sections(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    proposal = reflect_project(
        root,
        "Keep token fingerprints server-side",
        "diff --git a/src/sample/auth.py b/src/sample/auth.py\n+++ b/src/sample/auth.py\n",
    )
    body = (root / proposal["proposal"]).read_text(encoding="utf-8")
    for section in ("## Decision", "## Rationale", "## Alternatives", "## Consequences", "## Open questions"):
        assert section in body
    assert "<!-- agent:" in body
    assert proposal["agent_brief"]["sections_to_complete"]


def test_reflection_includes_untracked_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / "new_feature.py").write_text("VALUE = 1\n", encoding="utf-8")
    result = reflect_project(root, "Capture the production hardening learning")
    assert "new_feature.py" in result["changed_paths"]
    assert result["requires_review"]
    assert result["baseline"] == "none"
    assert result["warnings"]
