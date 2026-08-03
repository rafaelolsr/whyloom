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


def _write_record(root, name, *, record_id, status, confidence=None):
    (root / ".whyloom" / "architecture").mkdir(parents=True, exist_ok=True)
    conf = f"confidence: {confidence}\n" if confidence else ""
    (root / ".whyloom" / "architecture" / name).write_text(
        f"---\nid: {record_id}\ntype: architecture\ntitle: Shell\nstatus: {status}\n"
        f"date: 2026-07-31\ntargets:\n- src/auth.py\nconstraints: []\nsupersedes: []\n{conf}---\n\n"
        "## Observation\nx\n## Inference\nx\n## Consequences\nx\n",
        encoding="utf-8",
    )


def test_validate_flags_confidence_bearing_record_accepted_without_review(tmp_path):
    # Trust gate: a record still carrying a machine-confidence score reached an
    # authoritative status without passing review. Pilot regression: bootstrap
    # left ARC-INFERRED records at status: accepted with confidence intact.
    from whyloom.operations import validate_project

    root = _repo(tmp_path)
    _write_record(root, "0001-shell.md", record_id="ARC-INFERRED-001", status="accepted", confidence="high")
    result = validate_project(root, DEFAULT_CONFIG)
    assert not result["valid"]
    assert any(e["code"] == "TRUST001" for e in result["errors"])


def test_validate_allows_confidence_record_that_stays_proposed(tmp_path):
    from whyloom.operations import validate_project

    root = _repo(tmp_path)
    _write_record(root, "0001-shell.md", record_id="ARC-INFERRED-001", status="proposed", confidence="high")
    result = validate_project(root, DEFAULT_CONFIG)
    assert not any(e["code"] == "TRUST001" for e in result["errors"])


def test_validate_allows_inferred_id_accepted_without_confidence(tmp_path):
    # The INFERRED id records who DRAFTED the record (an agent); it must not gate
    # acceptance. A human-accepted record has its confidence stripped and is then
    # authoritative even though its id still says INFERRED.
    from whyloom.operations import validate_project

    root = _repo(tmp_path)
    _write_record(root, "0001-shell.md", record_id="ARC-INFERRED-001", status="accepted")
    result = validate_project(root, DEFAULT_CONFIG)
    assert not any(e["code"] == "TRUST001" for e in result["errors"])


def test_accept_strips_confidence_so_validate_passes(tmp_path):
    # Accepting an inferred proposal is the human gate: it must clear the machine
    # confidence so the record no longer trips TRUST001. Regression: accept flipped
    # status but left confidence, making the accepted record permanently invalid.
    from whyloom.operations import accept_records, validate_project

    root = _repo(tmp_path)
    (root / ".whyloom" / "proposals").mkdir(parents=True, exist_ok=True)
    (root / ".whyloom" / "proposals" / "shell.md").write_text(
        "---\nid: ARC-INFERRED-001\ntype: architecture\ntitle: Shell\nstatus: proposed\n"
        "date: 2026-07-31\ntargets:\n- src/auth.py\nconstraints: []\nsupersedes: []\nconfidence: high\n---\n\n"
        "## Observation\nx\n## Inference\nx\n## Consequences\nx\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    result = accept_records(root, DEFAULT_CONFIG, ids=["ARC-INFERRED-001"])
    assert result["accepted_count"] == 1

    text = (root / ".whyloom" / "proposals" / "shell.md").read_text(encoding="utf-8")
    assert "status: accepted" in text
    assert "confidence:" not in text

    validation = validate_project(root, DEFAULT_CONFIG)
    assert not any(e["code"] == "TRUST001" for e in validation["errors"])
