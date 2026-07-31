import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from whyloom.cli import app
from whyloom.config import DEFAULT_CONFIG, WhyloomConfig, load_config
from whyloom.indexer import index_project
from whyloom.operations import doctor_project
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def test_version_flag_works_without_command():
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert result.stdout.strip() == "0.6.0"


def test_config_rejects_paths_outside_repository():
    with pytest.raises(ValidationError):
        WhyloomConfig(database="../outside.sqlite")
    with pytest.raises(ValidationError):
        WhyloomConfig(records_dir="/tmp/records")
    with pytest.raises(ValidationError):
        WhyloomConfig(include=["../**/*.py"])


def test_config_rejects_symlink_escape(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "records").symlink_to(outside, target_is_directory=True)
    (root / "whyloom.yaml").write_text("records_dir: records\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside repository"):
        load_config(root)


def test_read_command_does_not_create_missing_index(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    database = root / DEFAULT_CONFIG["database"]
    result = CliRunner().invoke(app, ["context", "token storage", "--root", str(root), "--json"])
    assert result.exit_code == 2
    assert not database.exists()
    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "IDX001"


def test_invalid_record_aborts_before_database_write(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    record = root / ".whyloom" / "decisions" / "0001-token-storage.md"
    record.write_text(record.read_text(encoding="utf-8").replace("id: DEC-0001", "id: '../escape'"), encoding="utf-8")
    result = index_project(root, DEFAULT_CONFIG)
    assert not result["indexed"]
    assert not (root / DEFAULT_CONFIG["database"]).exists()
    assert any(item["code"] == "REC001" for item in result["diagnostics"])


def test_index_honors_include_and_exclude_patterns(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / ".whyloom").mkdir()
    (root / "src" / "keep.py").write_text("def keep():\n    return True\n", encoding="utf-8")
    (root / "src" / "ignore.py").write_text("def ignore():\n    return True\n", encoding="utf-8")
    config = {**DEFAULT_CONFIG, "include": ["src/*.py"], "exclude": ["src/ignore.py"]}
    result = index_project(root, config)
    assert result["indexed"]
    with GraphStore(root / config["database"], create=False) as store:
        assert store.node("src/keep.py") is not None
        assert store.node("src/ignore.py") is None


def test_doctor_reports_ready_after_index(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    (root / "whyloom.yaml").write_text("version: 1\n", encoding="utf-8")
    index_project(root, DEFAULT_CONFIG)
    result = doctor_project(root, DEFAULT_CONFIG)
    assert result["ready"]
    assert all(check["ok"] for check in result["checks"])


def test_schema_migrates_existing_v1_database(tmp_path):
    database = tmp_path / "graph.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE migration_history (version INTEGER PRIMARY KEY, applied_at TEXT)")
    connection.execute("INSERT INTO migration_history(version, applied_at) VALUES (1, 'now')")
    connection.execute("CREATE TABLE sources (path TEXT PRIMARY KEY, hash TEXT, kind TEXT, indexed_at TEXT)")
    connection.commit()
    connection.close()

    with GraphStore(database, create=False) as store:
        columns = {row[1] for row in store.connection.execute("PRAGMA table_info(sources)")}
        version = store.connection.execute("SELECT MAX(version) FROM migration_history").fetchone()[0]
    assert "index_version" in columns
    assert version == 3


def test_index_format_upgrade_forces_reindex(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    first = index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        store.connection.execute("UPDATE sources SET index_version = 0")
        store.connection.commit()
    doctor = doctor_project(root, DEFAULT_CONFIG)
    second = index_project(root, DEFAULT_CONFIG)
    assert first["indexed"]
    assert not doctor["ready"]
    assert second["changed"]
