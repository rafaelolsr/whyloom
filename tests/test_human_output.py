"""Human-readable output: default mode is scannable text, --json is unchanged."""

import json

from whyloom.cli import render_human


def test_install_renders_as_lines():
    payload = {
        "operation": "install",
        "results": [{"platform": "claude", "skill": "whyloom", "destination": "/x/.claude/skills/whyloom", "action": "updated"}],
        "guidance": [{"platform": "claude", "file": "CLAUDE.md", "action": "appended"}],
    }
    text = render_human(payload)
    assert "Installed Whyloom skills:" in text
    assert "whyloom" in text and "guidance" in text
    assert "{" not in text  # not raw JSON


def test_doctor_renders_checklist():
    payload = {"ready": True, "checks": [{"name": "index", "ok": True, "detail": "graph.sqlite"}]}
    text = render_human(payload)
    assert text.startswith("✓ Ready")
    assert "✓ index" in text


def test_error_renders_concisely():
    payload = {"ok": False, "error": {"code": "IDX001", "message": "no index"}}
    assert render_human(payload) == "✗ IDX001: no index"


def test_context_lists_records_and_proposed():
    payload = {
        "task": "auth",
        "governing_records": [],
        "proposed_records": [{"id": "PROP-1", "title": "server-side tokens"}],
        "files": ["src/auth.py"],
        "warnings": ["review before trusting"],
    }
    text = render_human(payload)
    assert "Task: auth" in text
    assert "Proposed (unreviewed) (1):" in text
    assert "PROP-1" in text
    assert "⚠ review before trusting" in text


def test_unknown_shape_falls_back_to_json():
    payload = {"some": "unmapped", "shape": [1, 2, 3]}
    text = render_human(payload)
    # Valid JSON, since there is no dedicated renderer.
    assert json.loads(text) == payload
