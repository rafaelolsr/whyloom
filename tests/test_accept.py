"""Optional bulk accept: flip proposed records to accepted, preserving the file.
Editing status in a PR remains the primary human-review gate; this is CLI sugar."""

from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.operations import accept_records, init_project, propose_from_rationale

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _repo_with_proposal(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def f():\n    # WHY: keep it simple\n    return 1\n", encoding="utf-8")
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    propose_from_rationale(root, DEFAULT_CONFIG)
    return root


def test_accept_all_flips_status_and_preserves_file(tmp_path):
    root = _repo_with_proposal(tmp_path)
    proposal = next(root.glob(".whyloom/proposals/*.md"))
    before = proposal.read_text(encoding="utf-8")
    assert "status: proposed" in before

    result = accept_records(root, DEFAULT_CONFIG, all_proposed=True)
    assert result["accepted_count"] == 1
    after = proposal.read_text(encoding="utf-8")
    assert "status: accepted" in after
    # Only status changed; id/title/body preserved.
    assert "id:" in after and "## Rationale" in after
    assert before.replace("status: proposed", "status: accepted") == after


def test_accept_by_id_and_idempotent(tmp_path):
    root = _repo_with_proposal(tmp_path)
    proposal = next(root.glob(".whyloom/proposals/*.md"))
    record_id = next(line.split(":", 1)[1].strip() for line in proposal.read_text().splitlines() if line.startswith("id:"))

    first = accept_records(root, DEFAULT_CONFIG, ids=[record_id])
    assert first["accepted_count"] == 1

    # Re-accepting is a clean skip, not a phantom 'not found'.
    second = accept_records(root, DEFAULT_CONFIG, ids=[record_id])
    assert second["accepted_count"] == 0
    reasons = [s["reason"] for s in second["skipped"]]
    assert reasons == ["already accepted"]


def test_accept_missing_id_reports_not_found(tmp_path):
    root = _repo_with_proposal(tmp_path)
    result = accept_records(root, DEFAULT_CONFIG, ids=["DEC-9999"])
    assert result["accepted_count"] == 0
    assert any(s["id"] == "DEC-9999" and s["reason"] == "not found" for s in result["skipped"])
