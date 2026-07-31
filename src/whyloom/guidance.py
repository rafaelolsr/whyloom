"""Inject a Whyloom pointer into a project's agent-instruction file.

The skill's description alone is a probabilistic trigger: an agent may not think a
task touches recorded decisions and skip Whyloom entirely — missing the two
moments its value depends on (query before editing, capture after). A pointer in
the always-in-context instruction file (CLAUDE.md / AGENTS.md /
copilot-instructions.md) makes the pre-flight and capture steps non-optional.

The block is delimited by sentinels so it can be updated or removed idempotently
without touching anything else the user wrote in the file."""

from __future__ import annotations

from pathlib import Path

from .installer import AssistantPlatform

BEGIN = "<!-- whyloom:begin -->"
END = "<!-- whyloom:end -->"

# One instruction file per assistant family.
MEMORY_FILES = {
    AssistantPlatform.CLAUDE: "CLAUDE.md",
    AssistantPlatform.CODEX: "AGENTS.md",
    AssistantPlatform.AGENTS: "AGENTS.md",
    AssistantPlatform.COPILOT: ".github/copilot-instructions.md",
}

_BLOCK_BODY = """## Project memory (Whyloom)

This repository uses Whyloom for governed project memory. Follow this loop:

- **Before** changing rationale-sensitive or unfamiliar code, run
  `whyloom context "<task>" --compact --json` and prefer cited records over
  guessing intent from code shape.
- Use `whyloom explain <path>` and `whyloom path <a> <b>` to trace why code
  exists and how entities connect.
- **After** completing work, run `whyloom learnings --changed --json`; for
  significant uncovered changes run `whyloom reflect --task-summary "<what and why>"`
  and complete the proposal. Never accept a record without human review.
- Treat `INFERRED`/`AMBIGUOUS` edges as prompts to verify against the cited files.
"""


def guidance_block() -> str:
    return f"{BEGIN}\n{_BLOCK_BODY}{END}\n"


def memory_file_for(platform: AssistantPlatform) -> str | None:
    return MEMORY_FILES.get(platform)


def inject_guidance(root: Path, platform: AssistantPlatform) -> dict:
    """Idempotently add or update the Whyloom block in the platform's memory
    file. Preserves everything outside the sentinels; never clobbers user text."""
    filename = memory_file_for(platform)
    if filename is None:
        return {"platform": platform.value, "action": "skipped", "reason": "no memory file for platform"}
    path = root / filename
    block = guidance_block()

    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(block, encoding="utf-8")
        return {"platform": platform.value, "file": filename, "action": "created"}

    existing = path.read_text(encoding="utf-8")
    if BEGIN in existing and END in existing:
        head, _, rest = existing.partition(BEGIN)
        _, _, tail = rest.partition(END)
        updated = head + block.rstrip("\n") + tail
        if updated == existing:
            return {"platform": platform.value, "file": filename, "action": "unchanged"}
        path.write_text(updated, encoding="utf-8")
        return {"platform": platform.value, "file": filename, "action": "updated"}

    # Append below the user's own content, separated by a blank line.
    separator = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    path.write_text(existing + separator + block, encoding="utf-8")
    return {"platform": platform.value, "file": filename, "action": "appended"}


def remove_guidance(root: Path, platform: AssistantPlatform) -> dict:
    """Remove only the Whyloom-delimited block; leave the rest of the file and
    delete the file only if it becomes empty."""
    filename = memory_file_for(platform)
    if filename is None:
        return {"platform": platform.value, "action": "skipped"}
    path = root / filename
    if not path.exists():
        return {"platform": platform.value, "file": filename, "action": "absent"}
    existing = path.read_text(encoding="utf-8")
    if BEGIN not in existing or END not in existing:
        return {"platform": platform.value, "file": filename, "action": "not-managed"}
    head, _, rest = existing.partition(BEGIN)
    _, _, tail = rest.partition(END)
    remainder = (head.rstrip() + "\n" + tail.lstrip()).strip()
    if remainder:
        path.write_text(remainder + "\n", encoding="utf-8")
        return {"platform": platform.value, "file": filename, "action": "removed-block"}
    path.unlink()
    return {"platform": platform.value, "file": filename, "action": "removed-file"}
