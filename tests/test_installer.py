import json
from pathlib import Path

from typer.testing import CliRunner

from whyloom.cli import app
from whyloom.installer import AssistantPlatform, install_skills, resolve_destinations, uninstall_skills

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def test_copilot_project_install_is_idempotent_and_removable(tmp_path):
    first = install_skills(
        AssistantPlatform.COPILOT,
        project=True,
        root=tmp_path,
        home=tmp_path / "home",
        source_root=SKILLS,
    )
    assert {item["action"] for item in first["results"]} == {"installed"}
    for skill in ("whyloom", "whyloom-bootstrap"):
        destination = tmp_path / ".github" / "skills" / skill
        assert (destination / "SKILL.md").is_file()
        marker = json.loads((destination / ".whyloom-managed.json").read_text(encoding="utf-8"))
        assert marker["skill"] == skill

    second = install_skills(
        AssistantPlatform.COPILOT,
        project=True,
        root=tmp_path,
        home=tmp_path / "home",
        source_root=SKILLS,
    )
    assert {item["action"] for item in second["results"]} == {"unchanged"}
    removed = uninstall_skills(
        AssistantPlatform.COPILOT,
        project=True,
        root=tmp_path,
        home=tmp_path / "home",
    )
    assert {item["action"] for item in removed["results"]} == {"removed"}
    assert not (tmp_path / ".github" / "skills" / "whyloom").exists()


def test_installer_refuses_unowned_destination(tmp_path):
    destination = tmp_path / ".agents" / "skills" / "whyloom"
    destination.mkdir(parents=True)
    (destination / "SKILL.md").write_text("user-owned\n", encoding="utf-8")
    try:
        install_skills(
            AssistantPlatform.AGENTS,
            project=True,
            root=tmp_path,
            home=tmp_path / "home",
            source_root=SKILLS,
        )
    except ValueError as exc:
        assert "refusing to overwrite unowned" in str(exc)
    else:
        raise AssertionError("installer overwrote an unowned skill")
    assert (destination / "SKILL.md").read_text(encoding="utf-8") == "user-owned\n"


def test_installer_refuses_symlinked_destination(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    base = tmp_path / ".github" / "skills"
    base.mkdir(parents=True)
    (base / "whyloom").symlink_to(outside, target_is_directory=True)
    try:
        install_skills(
            AssistantPlatform.COPILOT,
            project=True,
            root=tmp_path,
            home=tmp_path / "home",
            source_root=SKILLS,
        )
    except ValueError as exc:
        assert "symlinked skill directory" in str(exc)
    else:
        raise AssertionError("installer followed a symlinked destination")


def test_auto_global_install_detects_codex_and_copilot(tmp_path):
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".copilot").mkdir()
    destinations = resolve_destinations(
        AssistantPlatform.AUTO,
        project=False,
        root=tmp_path,
        home=home,
        environment={},
    )
    assert destinations == [
        (AssistantPlatform.CODEX, home / ".codex" / "skills"),
        (AssistantPlatform.COPILOT, home / ".copilot" / "skills"),
    ]


def test_explicit_platform_locations(tmp_path):
    home = tmp_path / "home"
    expected = {
        AssistantPlatform.AGENTS: (tmp_path / ".agents" / "skills", home / ".agents" / "skills"),
        AssistantPlatform.CLAUDE: (tmp_path / ".claude" / "skills", home / ".claude" / "skills"),
        AssistantPlatform.CODEX: (tmp_path / ".agents" / "skills", home / ".codex" / "skills"),
        AssistantPlatform.COPILOT: (tmp_path / ".github" / "skills", home / ".copilot" / "skills"),
    }
    for platform, (project_path, global_path) in expected.items():
        assert resolve_destinations(platform, project=True, root=tmp_path, home=home, environment={}) == [
            (platform, project_path)
        ]
        assert resolve_destinations(platform, project=False, root=tmp_path, home=home, environment={}) == [
            (platform, global_path)
        ]


def test_install_cli_supports_copilot_project_scope(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(
        app,
        ["install", "--platform", "copilot", "--project", "--root", str(tmp_path), "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["operation"] == "install"
    assert {item["platform"] for item in payload["results"]} == {"copilot"}
    assert (tmp_path / ".github" / "skills" / "whyloom" / "SKILL.md").is_file()
