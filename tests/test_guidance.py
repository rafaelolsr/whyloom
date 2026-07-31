from pathlib import Path

from whyloom.guidance import (
    BEGIN,
    END,
    guidance_block,
    inject_guidance,
    memory_file_for,
    remove_guidance,
)
from whyloom.installer import AssistantPlatform, install_skills, uninstall_skills

SKILLS = Path(__file__).resolve().parents[1] / "skills"


def test_memory_file_per_platform():
    assert memory_file_for(AssistantPlatform.CLAUDE) == "CLAUDE.md"
    assert memory_file_for(AssistantPlatform.CODEX) == "AGENTS.md"
    assert memory_file_for(AssistantPlatform.AGENTS) == "AGENTS.md"
    assert memory_file_for(AssistantPlatform.COPILOT) == ".github/copilot-instructions.md"


def test_inject_creates_file(tmp_path):
    result = inject_guidance(tmp_path, AssistantPlatform.CLAUDE)
    assert result["action"] == "created"
    content = (tmp_path / "CLAUDE.md").read_text()
    assert BEGIN in content and END in content
    assert "whyloom context" in content


def test_inject_appends_and_is_idempotent(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# My project\n\nUser text.\n", encoding="utf-8")
    first = inject_guidance(tmp_path, AssistantPlatform.CLAUDE)
    assert first["action"] == "appended"
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "User text." in content
    assert content.count(BEGIN) == 1

    second = inject_guidance(tmp_path, AssistantPlatform.CLAUDE)
    assert second["action"] == "unchanged"
    assert (tmp_path / "CLAUDE.md").read_text().count(BEGIN) == 1


def test_inject_updates_stale_block(tmp_path):
    stale = f"# P\n\n{BEGIN}\nold content\n{END}\n"
    (tmp_path / "CLAUDE.md").write_text(stale, encoding="utf-8")
    result = inject_guidance(tmp_path, AssistantPlatform.CLAUDE)
    assert result["action"] == "updated"
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "old content" not in content
    assert "whyloom context" in content
    assert content.count(BEGIN) == 1


def test_remove_preserves_user_content(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("# My project\n\nKeep me.\n", encoding="utf-8")
    inject_guidance(tmp_path, AssistantPlatform.CLAUDE)
    result = remove_guidance(tmp_path, AssistantPlatform.CLAUDE)
    assert result["action"] == "removed-block"
    content = (tmp_path / "CLAUDE.md").read_text()
    assert "Keep me." in content
    assert BEGIN not in content


def test_remove_deletes_file_when_only_block(tmp_path):
    inject_guidance(tmp_path, AssistantPlatform.CLAUDE)
    result = remove_guidance(tmp_path, AssistantPlatform.CLAUDE)
    assert result["action"] == "removed-file"
    assert not (tmp_path / "CLAUDE.md").exists()


def test_install_injects_guidance_per_platform(tmp_path):
    result = install_skills(
        AssistantPlatform.COPILOT, project=True, root=tmp_path, source_root=SKILLS
    )
    guidance = result["guidance"]
    assert guidance and guidance[0]["file"] == ".github/copilot-instructions.md"
    assert (tmp_path / ".github" / "copilot-instructions.md").exists()


def test_install_no_guidance_flag(tmp_path):
    result = install_skills(
        AssistantPlatform.CLAUDE, project=True, root=tmp_path, source_root=SKILLS, guidance=False
    )
    assert result["guidance"] == []
    assert not (tmp_path / "CLAUDE.md").exists()


def test_uninstall_removes_guidance(tmp_path):
    install_skills(AssistantPlatform.CLAUDE, project=True, root=tmp_path, source_root=SKILLS)
    assert (tmp_path / "CLAUDE.md").exists()
    uninstall_skills(AssistantPlatform.CLAUDE, project=True, root=tmp_path)
    assert not (tmp_path / "CLAUDE.md").exists()


def test_guidance_block_has_sentinels():
    block = guidance_block()
    assert block.startswith(BEGIN)
    assert block.rstrip().endswith(END)
