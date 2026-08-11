import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_release_workflow_uses_pypi_trusted_publishing():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "types: [published]" in workflow
    assert "environment: pypi" in workflow
    assert "id-token: write" in workflow
    assert "pypa/gh-action-pypi-publish@release/v1" in workflow
    assert "actions/upload-artifact@v4" in workflow
    assert "actions/download-artifact@v4" in workflow


def test_package_metadata_points_to_public_repository():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert project["name"] == "whyloom"
    assert project["urls"]["Repository"] == "https://github.com/rafaelolsr/whyloom.git"


def test_version_is_consistent_and_changelogged():
    # The version must match across pyproject.toml and __init__.py, and have a
    # CHANGELOG entry — so a release is never ambiguous about what it contains.
    # (A hardcoded literal here just re-broke on every bump; consistency is the
    # real invariant.)
    import re

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    init_src = (ROOT / "src" / "whyloom" / "__init__.py").read_text(encoding="utf-8")
    init_version = re.search(r'__version__\s*=\s*"([^"]+)"', init_src).group(1)
    assert pyproject == init_version, f"pyproject {pyproject} != __init__ {init_version}"
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## {pyproject}" in changelog, f"CHANGELOG.md has no entry for {pyproject}"


def test_bundled_skills_complete_pending_onboarding_without_a_user_prompt():
    ongoing = (ROOT / "skills" / "whyloom" / "SKILL.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "skills" / "whyloom-bootstrap" / "SKILL.md").read_text(encoding="utf-8")

    assert "whyloom onboard --status --json" in ongoing
    assert "Do not wait" in ongoing
    assert "invoke `$whyloom-bootstrap`" in ongoing
    assert "whyloom onboard --status --root <root> --json" in bootstrap
    assert "whyloom onboard --complete" in bootstrap
    assert ".whyloom/cache/bootstrap/request.json" in bootstrap
    assert ".whyloom/cache/coverage.json" in bootstrap
    assert "relationship evidence and provenance" in ongoing
