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


def test_report_renders_god_nodes():
    payload = {
        "totals": {"nodes": 100, "edges": 200, "accepted_records": 1},
        "god_nodes": [{"label": "AdvisorState", "type": "Symbol", "degree": 460}],
        "suggested_questions": ["Why does AdvisorState exist?"],
        "node_types": {"Symbol": 50},
    }
    text = render_human(payload)
    assert "Most-connected entities:" in text
    assert "AdvisorState" in text and "460 connections" in text
    assert "Suggested questions:" in text
    assert "{" not in text


def test_reflect_command_accepts_positional_and_option(tmp_path):
    # 'whyloom reflect "did X"' must work; --task-summary stays as an alias;
    # bare 'reflect' gives a helpful error, not a raw Typer stack (pilot friction).
    from typer.testing import CliRunner

    from whyloom.cli import app

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    runner = CliRunner()
    runner.invoke(app, ["init", str(tmp_path)])
    runner.invoke(app, ["index", "--root", str(tmp_path)])

    positional = runner.invoke(app, ["reflect", "added a thing", "--root", str(tmp_path), "--json"])
    assert positional.exit_code == 0 and '"status": "proposed"' in positional.stdout

    option = runner.invoke(app, ["reflect", "--task-summary", "alias works", "--root", str(tmp_path), "--json"])
    assert option.exit_code == 0

    bare = runner.invoke(app, ["reflect", "--root", str(tmp_path)])
    assert bare.exit_code != 0
    assert "REFLECT001" in bare.stdout


def test_reflect_renders_human():
    payload = {"proposal": ".whyloom/proposals/x.md", "status": "proposed", "changed_paths": ["src/a.py"]}
    text = render_human(payload)
    assert "Drafted proposal" in text and "x.md" in text
    assert "{" not in text
