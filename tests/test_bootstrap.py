import json
import subprocess
from pathlib import Path

from typer.testing import CliRunner

from whyloom.bootstrap import bootstrap_project
from whyloom.cli import app
from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.records import parse_record
from whyloom.store import GraphStore


def make_existing_repository(tmp_path: Path) -> Path:
    root = tmp_path / "existing"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / "docs" / "adr").mkdir(parents=True)
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / "src" / "service.py").write_text(
        "# We must keep writes atomic because partial state is unsafe.\n"
        "def update():\n"
        "    return 'ok'\n",
        encoding="utf-8",
    )
    (root / "tests" / "test_service.py").write_text(
        "from src.service import update\n\ndef test_update():\n    assert update() == 'ok'\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text("# Existing service\n\n## Architecture\n\nA small service.\n", encoding="utf-8")
    (root / "docs" / "adr" / "0001-atomic.md").write_text("# Use atomic writes\n", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]\nname = 'existing'\n", encoding="utf-8")
    (root / ".github" / "workflows" / "ci.yml").write_text("name: CI\n", encoding="utf-8")
    (root / ".env").write_text("SECRET=do-not-copy\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "user.name=Whyloom Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "Choose atomic updates for crash safety",
        ],
        cwd=root,
        check=True,
    )
    return root


def test_bootstrap_collects_bounded_evidence_without_changing_records(tmp_path):
    root = make_existing_repository(tmp_path)
    result = bootstrap_project(root, DEFAULT_CONFIG, history_limit=10, max_evidence=100)

    assert result["bootstrapped"]
    assert result["canonical_records_changed"] is False
    assert not (root / "whyloom").exists()
    expected = {"documentation", "test", "configuration", "dependency", "git-history", "rationale-comment"}
    assert expected <= set(result["coverage"])
    manifest = json.loads((root / result["manifest"]).read_text(encoding="utf-8"))
    assert manifest["authoritative"] is False
    assert "do-not-copy" not in json.dumps(manifest)
    assert all(len(item["summary"]) <= 240 for item in manifest["evidence"])
    report = (root / result["report"]).read_text(encoding="utf-8")
    assert "not authoritative" in report
    assert "Require human review" in report


def test_bootstrap_is_deterministic_for_unchanged_repository(tmp_path):
    root = make_existing_repository(tmp_path)
    first = bootstrap_project(root, DEFAULT_CONFIG)
    first_manifest = (root / first["manifest"]).read_text(encoding="utf-8")
    second = bootstrap_project(root, DEFAULT_CONFIG)
    second_manifest = (root / second["manifest"]).read_text(encoding="utf-8")
    assert first_manifest == second_manifest
    assert second["index"]["changed"] == []


def test_bootstrap_cli_emits_machine_readable_contract(tmp_path):
    root = make_existing_repository(tmp_path)
    result = CliRunner().invoke(app, ["bootstrap", "--root", str(root), "--json", "--history-limit", "1"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["bootstrapped"] is True
    assert payload["manifest"] == ".whyloom/bootstrap/evidence.json"
    assert payload["canonical_records_changed"] is False


def test_inferred_record_metadata_is_indexed_as_non_governing(tmp_path):
    root = tmp_path / "repo"
    proposal = root / "whyloom" / "proposals" / "inferred-architecture.md"
    proposal.parent.mkdir(parents=True)
    (root / "src").mkdir()
    (root / "src" / "service.py").write_text("def service():\n    return True\n", encoding="utf-8")
    proposal.write_text(
        "---\n"
        "id: ARC-INFERRED-001\n"
        "type: architecture\n"
        "title: Service boundary inferred from package layout\n"
        "status: proposed\n"
        "confidence: medium\n"
        "targets: [src/service.py]\n"
        "evidence:\n"
        "  - kind: code\n"
        "    source: src/service.py\n"
        "    summary: Defines the visible service entry point.\n"
        "open_questions:\n"
        "  - Is this boundary intentional or incidental?\n"
        "---\n\n"
        "This is an inference for review, not an accepted description.\n",
        encoding="utf-8",
    )

    record = parse_record(proposal, root)
    assert record.confidence.value == "medium"
    assert record.evidence[0].source == "src/service.py"
    result = index_project(root, DEFAULT_CONFIG)
    assert result["indexed"]
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        node = store.node("ARC-INFERRED-001")
    assert node["data"]["status"] == "proposed"
    assert node["data"]["confidence"] == "medium"
    assert node["data"]["open_questions"] == ["Is this boundary intentional or incidental?"]
