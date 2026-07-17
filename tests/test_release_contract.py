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
    assert project["version"] == "0.5.1"
    assert project["urls"]["Repository"] == "https://github.com/rafaelolsr/whyloom.git"


def test_bundled_skills_complete_pending_onboarding_without_a_user_prompt():
    ongoing = (ROOT / "skills" / "whyloom" / "SKILL.md").read_text(encoding="utf-8")
    bootstrap = (ROOT / "skills" / "whyloom-bootstrap" / "SKILL.md").read_text(encoding="utf-8")

    assert "whyloom onboard --status --json" in ongoing
    assert "Do not wait" in ongoing
    assert "invoke `$whyloom-bootstrap`" in ongoing
    assert "whyloom onboard --status --root <root> --json" in bootstrap
    assert "whyloom onboard --complete" in bootstrap
    assert ".whyloom/cache/bootstrap/request.json" in bootstrap
