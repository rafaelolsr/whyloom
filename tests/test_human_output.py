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


def test_explain_renders_structured_brief():
    payload = {
        "found": True,
        "target": "src/workflows/router.py",
        "governing_records": [
            {
                "id": "ARC-0001",
                "type": "Architecture",
                "status": "accepted",
                "provenance": "human-authored",
                "title": "Deterministic workflow shell",
                "why": "The app does not delegate orchestration to one agent.",
                "decision": "A deterministic shell around bounded agents.",
                "consequences": "- New paths are modules.\n- Cross-path code lives in SharedServices.",
                "targets": ["src/workflows/router.py"],
                "open_questions": ["Is General QA a permanent path?"],
            }
        ],
        "knowledge_gaps": [],
        "warnings": [],
    }
    text = render_human(payload)
    assert "▸ src/workflows/router.py" in text
    assert "ARC-0001 · accepted · human-authored" in text
    assert "Why it exists:" in text and "What it does:" in text and "Trade-offs & limits:" in text
    assert "Applies to: src/workflows/router.py" in text
    assert "? Is General QA a permanent path?" in text
    assert "{" not in text  # not raw JSON


def test_explain_renders_gap_when_no_record():
    payload = {"found": True, "target": "src/x.py", "governing_records": [], "knowledge_gaps": ["No governing record is linked to this target."], "warnings": []}
    text = render_human(payload)
    assert "▸ src/x.py" in text
    assert "unrecorded" in text


def test_record_sections_parses_headings():
    from whyloom.records import record_sections

    body = "## Context\n\nWhy it exists.\n\n## Decision\n\nWhat we chose.\n\n## Consequences\n\n- a\n- b\n"
    sections = record_sections(body)
    assert sections["context"] == "Why it exists."
    assert sections["decision"] == "What we chose."
    assert "- a" in sections["consequences"]


def test_record_sections_collapses_placeholder_only_body():
    from whyloom.records import record_sections

    sections = record_sections("## Decision\n\n<!-- Restate the decision, then accept. -->\n")
    assert sections["decision"] == ""


def test_context_teaches_as_it_answers():
    payload = {
        "task": "auth",
        "governing_records": [],
        "proposed_records": [{"id": "PROP-1", "title": "server-side tokens"}],
        "files": ["src/auth.py"],
        "warnings": ["review before trusting"],
    }
    text = render_human(payload)
    # Answer-first: the relevant code is labeled and leads.
    assert "Task: auth" in text
    assert "Where to look" in text and "src/auth.py" in text
    # The rationale slot is explained, not a bare count; proposed records are shown
    # as an unreviewed starting point with the accept next-step.
    assert "proposed" in text.casefold() and "PROP-1" in text
    assert "whyloom accept" in text
    assert "⚠ review before trusting" in text


def test_context_explains_empty_rationale_with_next_step():
    # The common day-zero case (no records) must read as guidance, not an error.
    payload = {
        "task": "catalog pipeline",
        "governing_records": [],
        "proposed_records": [],
        "files": ["catalog/orchestrator/pipeline.py"],
        "warnings": ["No accepted decision or constraint was found for this task."],
    }
    text = render_human(payload)
    assert "Where to look" in text
    assert "none yet" in text and "whyloom reflect" in text
    # The bare "No accepted decision" warning is absorbed into the explanation,
    # not repeated as a scary trailing ⚠.
    assert "⚠ No accepted decision" not in text


def test_impact_reads_as_plain_language():
    payload = {
        "target": "src/workflows/router.py",
        "counts": {"records": 0, "symbols": 50, "callers": 2},
        "affected": {
            "downstream_callers": [{"label": "StarbaseWorkflow.__init__"}, {"label": "ProposalOrchestrator.__init__"}],
            "symbols": [{"name": "WorkflowRouter"}],
        },
    }
    text = render_human(payload)
    assert "Changing src/workflows/router.py affects" in text
    assert "2 production dependent(s)" in text and "StarbaseWorkflow.__init__" in text
    assert "No governing decision recorded" in text


def test_doctor_ends_with_plain_verdict_and_next_step():
    payload = {"ready": True, "checks": [{"name": "validation", "ok": True, "detail": "0 records"}]}
    text = render_human(payload)
    assert "Ready — Whyloom can answer" in text
    # The bare "0 records" is reframed as the normal day-zero state, not a defect.
    assert "no records yet" in text
    assert "whyloom context" in text  # a next step


def test_learnings_frames_uncovered_as_normal_not_a_todo_list():
    # Pilot confusion: "Uncovered source files: 1136" read as 1136 problems. The
    # whole-repo view must frame uncovered coverage as expected, not actionable.
    payload = {
        "proposal_count": 0,
        "uncovered_count": 1136,
        "uncovered": ["a.py", "b.py"],
        "changed_only": False,
        "index_present": True,
    }
    text = render_human(payload)
    assert "no proposals are pending" in text
    assert "1136 source file(s) have no recorded rationale" in text
    assert "normal" in text and "--changed" in text


def test_learnings_changed_lists_gaps_in_touched_files():
    payload = {
        "proposal_count": 2,
        "uncovered_count": 1,
        "uncovered": ["src/auth.py"],
        "changed_only": True,
        "index_present": True,
    }
    text = render_human(payload)
    assert "2 proposed record(s) awaiting your acceptance" in text
    assert "whyloom accept" in text
    assert "Rationale gaps in what you changed" in text and "src/auth.py" in text
    assert "whyloom reflect" in text


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
    assert positional.exit_code == 0 and '"status": "draft"' in positional.stdout

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
