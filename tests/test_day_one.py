"""Day-one value: proposed rationale from comments, surfaced in retrieval, and
an Obsidian export — all without breaking the human-review trust gate."""


from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.obsidian import export_obsidian
from whyloom.operations import init_project, propose_from_rationale
from whyloom.retrieval import context_packet
from whyloom.store import GraphStore


def _repo_with_rationale(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        "def login(user):\n"
        "    # WHY: refresh tokens stay server-side because XSS can read localStorage\n"
        "    return user\n",
        encoding="utf-8",
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    return root


def test_propose_creates_proposed_records(tmp_path):
    root = _repo_with_rationale(tmp_path)
    result = propose_from_rationale(root, DEFAULT_CONFIG)
    assert result["created_count"] >= 1
    proposal = next(iter(root.glob(".whyloom/proposals/prop-rationale-*.md")))
    text = proposal.read_text(encoding="utf-8")
    # The trust gate: auto-derived records are proposed, never accepted.
    assert "status: draft" in text
    assert "XSS can read localStorage" in text


def test_propose_is_idempotent(tmp_path):
    root = _repo_with_rationale(tmp_path)
    first = propose_from_rationale(root, DEFAULT_CONFIG)
    second = propose_from_rationale(root, DEFAULT_CONFIG)
    assert first["created_count"] >= 1
    assert second["created_count"] == 0
    assert second["skipped"] >= 1


def test_context_surfaces_proposed_but_not_as_governing(tmp_path):
    root = _repo_with_rationale(tmp_path)
    propose_from_rationale(root, DEFAULT_CONFIG)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        packet = context_packet(store, "login refresh token")
    # Proposed rationale is visible...
    assert packet["proposed_records"]
    assert all(r.get("data", {}).get("status") in {"draft", "proposed"} for r in packet["proposed_records"])
    # ...but never counted as governing (accepted) intent.
    assert packet["governing_records"] == []
    assert any("review before trusting" in w for w in packet["warnings"])


def test_export_obsidian_builds_linked_vault(tmp_path):
    root = _repo_with_rationale(tmp_path)
    propose_from_rationale(root, DEFAULT_CONFIG)
    index_project(root, DEFAULT_CONFIG)
    out = tmp_path / "vault"
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        result = export_obsidian(store, out)
    assert result["notes_written"] > 0
    assert (out / "README.md").exists()
    # Notes use Obsidian wikilinks for relationships.
    all_text = "\n".join(p.read_text(encoding="utf-8") for p in out.rglob("*.md"))
    assert "[[" in all_text and "]]" in all_text
    # Proposed records are labeled as unreviewed in the vault.
    assert "Draft" in all_text


def test_decision_comment_extracts_and_proposes(tmp_path):
    # A `# decision:` comment is the most natural whyloom rationale; it must
    # become a Rationale node and be proposable (regression: DECISION tag was
    # missing from RATIONALE_TAGS, so propose silently produced nothing).
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        "def rotate(user):\n    # decision: rotate on every use to shrink replay window\n    return user\n",
        encoding="utf-8",
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        rationale = [r["label"] for r in store.connection.execute("SELECT label FROM nodes WHERE type = 'Rationale'")]
    assert any(label.startswith("DECISION:") for label in rationale)

    result = propose_from_rationale(root, DEFAULT_CONFIG)
    assert result["created_count"] >= 1


def test_compact_context_surfaces_symbol_files(tmp_path):
    # A symbol hit must surface its containing file even if the File node was
    # not directly reached in traversal (pilot: files list came back empty).
    from whyloom.retrieval import compact_context_packet, context_packet

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "router.py").write_text(
        "class WorkflowRouter:\n    def dispatch(self, req):\n        return req\n", encoding="utf-8"
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"], create=False) as store:
        compact = compact_context_packet(context_packet(store, "workflow router dispatch"))
    assert any("router.py" in f for f in compact["files"])
    assert any(s["name"].startswith("WorkflowRouter") for s in compact["symbols"])


def test_propose_message_distinguishes_none_from_already_proposed(tmp_path):
    # "no proposals" must explain WHY: none exist vs all already proposed
    # (pilot confusion: message read like the repo had no rationale).
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def f():\n    # WHY: keep it simple\n    return 1\n", encoding="utf-8")
    init_project(root)
    index_project(root, DEFAULT_CONFIG)

    first = propose_from_rationale(root, DEFAULT_CONFIG)
    assert first["created_count"] == 1

    second = propose_from_rationale(root, DEFAULT_CONFIG)
    assert second["created_count"] == 0
    assert second["skipped"] >= 1
    assert "already proposed" in second["next_action"]

    # A repo with no proposable tags gets the other message.
    bare = tmp_path / "bare"
    (bare / "src").mkdir(parents=True)
    (bare / "src" / "b.py").write_text("def g():\n    return 1\n", encoding="utf-8")
    init_project(bare)
    index_project(bare, DEFAULT_CONFIG)
    result = propose_from_rationale(bare, DEFAULT_CONFIG)
    assert result["created_count"] == 0
    assert "no" in result["next_action"].casefold() and "found" in result["next_action"].casefold()
