import threading
from pathlib import Path

import pytest

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.locking import IndexLockTimeout, index_lock
from whyloom.operations import doctor_project, init_project, stale_sources
from whyloom.store import CorruptIndexError, GraphStore


def _repo(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("def rotate(user):\n    return user\n", encoding="utf-8")
    init_project(root)
    return root


def test_stale_sources_detects_edits(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        assert stale_sources(root, DEFAULT_CONFIG, store) == []
        (root / "src" / "auth.py").write_text("def rotate(user):\n    return user.upper()\n", encoding="utf-8")
        assert stale_sources(root, DEFAULT_CONFIG, store) == ["src/auth.py"]


def test_stale_sources_detects_deletion(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    (root / "src" / "auth.py").unlink()
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        assert "src/auth.py" in stale_sources(root, DEFAULT_CONFIG, store)


def test_index_lock_is_exclusive(tmp_path):
    lock = tmp_path / "index.lock"
    with index_lock(lock, timeout=1.0):
        with pytest.raises(IndexLockTimeout):
            with index_lock(lock, timeout=0.3, poll=0.05):
                pass
    # Released after the block: acquirable again.
    with index_lock(lock, timeout=1.0):
        pass


def test_concurrent_index_does_not_corrupt(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    for i in range(15):
        (root / "src" / f"m{i}.py").write_text(f"def f{i}():\n    return {i}\n", encoding="utf-8")
    init_project(root)

    errors = []

    def run():
        try:
            index_project(root, DEFAULT_CONFIG)
        except IndexLockTimeout:
            pass
        except Exception as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        assert store.integrity_ok()


def test_corrupt_index_raises_clean_error(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    db = root / DEFAULT_CONFIG["database"]
    data = bytearray(db.read_bytes())
    for i in range(100, min(len(data), 400)):
        data[i] = 0xFF
    db.write_bytes(bytes(data))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    with pytest.raises(CorruptIndexError):
        GraphStore(db, create=False)


def test_doctor_reports_corrupt_index(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    db = root / DEFAULT_CONFIG["database"]
    data = bytearray(db.read_bytes())
    for i in range(100, min(len(data), 400)):
        data[i] = 0xFF
    db.write_bytes(bytes(data))
    for suffix in ("-wal", "-shm"):
        sidecar = Path(str(db) + suffix)
        if sidecar.exists():
            sidecar.unlink()

    result = doctor_project(root, DEFAULT_CONFIG)
    integrity = next(check for check in result["checks"] if check["name"] == "integrity")
    assert not integrity["ok"]
    assert not result["ready"]


def test_doctor_reports_stale_freshness(tmp_path):
    root = _repo(tmp_path)
    index_project(root, DEFAULT_CONFIG)
    (root / "src" / "auth.py").write_text("def rotate(user):\n    return user.lower()\n", encoding="utf-8")
    result = doctor_project(root, DEFAULT_CONFIG)
    freshness = next(check for check in result["checks"] if check["name"] == "freshness")
    assert not freshness["ok"]


def test_learnings_reports_uncovered_source(tmp_path):
    from whyloom.operations import learnings_report

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("def rotate():\n    return 1\n", encoding="utf-8")
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    report = learnings_report(root, DEFAULT_CONFIG)
    assert report["index_present"]
    # A source file with no governing record is an uncovered rationale gap.
    assert "src/auth.py" in report["uncovered"]


def test_learnings_excludes_covered_files(tmp_path):
    from whyloom.operations import learnings_report

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text("def rotate():\n    return 1\n", encoding="utf-8")
    init_project(root)
    (root / ".whyloom" / "decisions").mkdir(parents=True, exist_ok=True)
    (root / ".whyloom" / "decisions" / "0001-auth.md").write_text(
        "---\nid: DEC-0001\ntype: decision\ntitle: Auth approach\nstatus: accepted\n"
        "date: 2026-07-31\ntargets:\n- src/auth.py\nconstraints: []\nsupersedes: []\n---\n\n"
        "## Context\nx\n## Decision\nx\n## Rationale\nx\n## Alternatives\nx\n## Consequences\nx\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    report = learnings_report(root, DEFAULT_CONFIG)
    # The covered file must not appear as a gap.
    assert "src/auth.py" not in report["uncovered"]
