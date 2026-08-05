import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.retrieval import compact_context_packet, context_packet, explain_target, find_path
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _repo_with_dir_target(tmp_path, target):
    from whyloom.operations import init_project

    root = tmp_path / "repo"
    (root / "catalog" / "orchestrator").mkdir(parents=True)
    (root / "catalog" / "orchestrator" / "pipeline.py").write_text(
        "class Pipeline:\n    def run(self):\n        return 1\n", encoding="utf-8"
    )
    (root / "catalog" / "query.py").write_text("def read():\n    return 2\n", encoding="utf-8")
    init_project(root)
    (root / ".whyloom" / "architecture").mkdir(parents=True, exist_ok=True)
    (root / ".whyloom" / "architecture" / "0001-cat.md").write_text(
        "---\nid: ARC-0001\ntype: architecture\ntitle: Catalog boundary\nstatus: accepted\n"
        f"date: 2026-08-04\ntargets:\n- {target}\nconstraints: []\nsupersedes: []\n---\n\n"
        "## Observation\nCatalog is a bounded context.\n## Inference\nOne package.\n## Consequences\nx\n",
        encoding="utf-8",
    )
    index_project(root, DEFAULT_CONFIG)
    return root


def test_directory_target_links_record_to_contained_files(tmp_path):
    # Pilot bug: a record targeting a directory (e.g. `catalog`) linked to a
    # phantom `file:catalog` node no file matched, orphaning the record so
    # retrieval never surfaced it — agents fell back to grep. The target must
    # expand to APPLIES_TO edges for every file under the directory.
    root = _repo_with_dir_target(tmp_path, "catalog")
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        targets = {
            row["target"]
            for row in store.connection.execute("SELECT target FROM edges WHERE source = 'ARC-0001' AND type = 'APPLIES_TO'")
        }
        packet = compact_context_packet(context_packet(store, "catalog pipeline run"))
    assert "file:catalog/orchestrator/pipeline.py" in targets
    assert "file:catalog/query.py" in targets
    assert "file:catalog" not in targets  # no phantom directory node
    # The record now surfaces as governing for a query about the contained code.
    assert any(r["id"] == "ARC-0001" for r in packet["governing_records"])


def test_file_target_is_unchanged(tmp_path):
    # A direct file target must still produce exactly one edge to that file.
    root = _repo_with_dir_target(tmp_path, "catalog/orchestrator/pipeline.py")
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        targets = [
            row["target"]
            for row in store.connection.execute("SELECT target FROM edges WHERE source = 'ARC-0001' AND type = 'APPLIES_TO'")
        ]
    assert targets == ["file:catalog/orchestrator/pipeline.py"]


def test_search_ranks_path_term_coverage_over_frequency(tmp_path):
    # Guardrail for term-coverage ranking: the file whose PATH covers more distinct
    # query terms must rank first. (The frequency pathology it guards against only
    # manifests at corpus scale, where term frequency swamps IDF; this small-repo
    # test locks in correct ordering and documents the intent rather than
    # reproducing the scale failure.)
    from whyloom.operations import init_project

    root = tmp_path / "repo"
    (root / "catalog" / "orchestrator").mkdir(parents=True)
    (root / "catalog" / "orchestrator" / "pipeline.py").write_text(
        "class Pipeline:\n    def run(self):\n        return 1\n", encoding="utf-8"
    )
    (root / "noise.py").write_text(
        "# ingestion ingestion ingestion ingestion ingestion ingestion\n"
        "def ingestion():\n    return 'ingestion ingestion ingestion'\n",
        encoding="utf-8",
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        results = store.search("catalog ingestion pipeline", 5)
    top_path = results[0].get("path") or results[0].get("source_path") or ""
    assert "catalog/orchestrator/pipeline.py" in top_path


def test_search_diversifies_so_a_sparse_relevant_file_surfaces(tmp_path):
    # Benchmark regression (T3): a symbol-dense file monopolized every result
    # slot, burying an equally relevant file with fewer symbols. Deep over-fetch
    # + per-file diversification must surface both.
    from whyloom.operations import init_project

    root = tmp_path / "repo"
    (root / "state").mkdir(parents=True)
    # Dense file: many symbols all matching "store".
    dense = "class ChatStore:\n" + "".join(f"    def op{i}(self):\n        return {i}\n" for i in range(20))
    (root / "state" / "conversation_store.py").write_text(dense, encoding="utf-8")
    # Sparse file: the class the query really wants, few symbols.
    (root / "state" / "store.py").write_text(
        "class ConversationStore:\n    def save(self):\n        return 1\n", encoding="utf-8"
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        paths = {r.get("path") or r.get("source_path") for r in store.search("conversation store", 10)}
    assert any(p and "state/store.py" in p for p in paths)
    assert any(p and "conversation_store.py" in p for p in paths)


def test_search_stems_natural_language_query(tmp_path):
    # A prose query ("how are records persisted") must find a symbol named for the
    # concept ("persist"), via deterministic stemming + FTS prefix matching — no
    # embeddings. Closes the phrasing-sensitivity gap for human-typed questions.
    from whyloom.operations import init_project
    from whyloom.store import _stem

    assert _stem("persisted") == "persist"
    assert _stem("persistence") == "persist"

    root = tmp_path / "repo"
    (root / "state").mkdir(parents=True)
    (root / "state" / "store.py").write_text(
        "class ConversationStore:\n    def persist(self, turn):\n        return 1\n", encoding="utf-8"
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        paths = {r.get("path") or r.get("source_path") for r in store.search("how are conversations persisted", 8)}
    assert any(p and "state/store.py" in p for p in paths)


def test_flow_traces_ordered_execution(tmp_path):
    # `flow` answers "how does it work" structurally: the ordered call skeleton
    # from an entry, resolved to real symbols, deterministic (no LLM).
    from whyloom.operations import init_project
    from whyloom.retrieval import flow_trace

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "steps.py").write_text(
        "def prepare():\n    return 1\ndef finish():\n    return 2\n", encoding="utf-8"
    )
    (root / "src" / "run.py").write_text(
        "from src.steps import prepare, finish\n\n"
        "def orchestrate():\n    prepare()\n    x = compute()\n    finish()\n    return x\n\n"
        "def compute():\n    return 3\n",
        encoding="utf-8",
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = flow_trace(store, "src/run.py")
    assert result["found"]
    # The behavioral entry (most calls) is orchestrate, and its calls are in order.
    assert "orchestrate" in result["entry"]
    names = [c["name"] for c in result["flow"]["calls"]]
    assert names == ["prepare", "compute", "finish"]
    # Calls into another file resolve to that file's path.
    prepare = next(c for c in result["flow"]["calls"] if c["name"] == "prepare")
    assert prepare["path"] and "steps.py" in prepare["path"]


def test_find_path_between_file_and_record(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = find_path(store, "src/sample/auth.py", "DEC-0001")
    assert result["found"]
    assert result["length"] >= 1
    assert result["endpoints"]["target"] == "DEC-0001"
    # Every hop names an edge type and provenance so the connection is auditable.
    for hop in result["hops"]:
        assert hop["type"]
        assert hop["provenance"] in {"EXTRACTED", "INFERRED", "AMBIGUOUS"}


def test_find_path_missing_endpoint(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = find_path(store, "src/sample/auth.py", "does-not-exist-xyz")
    assert not result["found"]
    assert result["warnings"]


def test_find_path_same_node(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = find_path(store, "src/sample/auth.py", "src/sample/auth.py")
    assert result["found"]
    assert result["length"] == 0


def test_index_context_and_explain(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    first = index_project(root, DEFAULT_CONFIG)
    second = index_project(root, DEFAULT_CONFIG)
    assert first["nodes_written"] >= 4
    assert first["indexed"]
    assert first["edges_written"] >= 4
    assert not second["changed"]
    assert second["unchanged"]

    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        packet = context_packet(store, "change token storage credentials")
        explanation = explain_target(store, "src/sample/auth.py")

    assert {item["id"] for item in packet["governing_records"]} == {"DEC-0001", "CON-0001"}
    assert explanation["found"]
    assert {item["id"] for item in explanation["governing_records"]} == {"DEC-0001", "CON-0001"}

    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        version = store.connection.execute("SELECT MAX(version) FROM migration_history").fetchone()[0]
        imports = store.connection.execute("SELECT target FROM edges WHERE type = 'IMPORTS'").fetchall()
    assert version == 3
    assert {row[0] for row in imports} == {"module-ref:src/sample/auth.py:hashlib"}

    compact = compact_context_packet(packet)
    assert compact["files"] == ["src/sample/auth.py"]
    assert {item["id"] for item in compact["governing_records"]} == {"DEC-0001", "CON-0001"}
    assert "evidence" not in compact


def test_impact_reports_only_real_dependents_not_keyword_matches(tmp_path):
    # Dogfooding bug: impact used a fuzzy graph walk that inflated "1 real caller"
    # into dozens of keyword-adjacent false positives (44 vs 1 on a real .mjs repo).
    # Guardrail that only true dependency edges count. (The full inflation needs
    # corpus scale to reproduce; this locks in correct dependent/decoy behavior.)
    from whyloom.operations import init_project
    from whyloom.retrieval import impact_analysis

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    # The target and its one real caller.
    (root / "src" / "adapter.py").write_text("def sync():\n    return 1\n", encoding="utf-8")
    (root / "src" / "app.py").write_text("from src.adapter import sync\n\ndef run():\n    return sync()\n", encoding="utf-8")
    # A decoy: mentions 'adapter'/'sync' by name but never imports the target.
    (root / "src" / "notes.py").write_text("# adapter sync adapter sync\ndef describe_sync():\n    return 'adapter sync'\n", encoding="utf-8")
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = impact_analysis(store, "src/adapter.py")
    caller_paths = {c["path"] for c in result["affected"]["downstream_callers"]}
    # The real caller is found; the keyword decoy is NOT reported as a dependent.
    assert any(p and "app.py" in p for p in caller_paths)
    assert not any(p and "notes.py" in p for p in caller_paths)


def test_impact_analysis_expands_files_to_symbols(tmp_path):
    from whyloom.retrieval import impact_analysis

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = impact_analysis(store, "CON-0001")
    assert result["found"]
    # Impact names concrete entities: the governed file's symbols, not just files.
    assert result["affected"]["symbols"]
    assert result["counts"]["symbols"] >= 1
    # Grouped output separates records, files, symbols, and callers.
    assert set(result["affected"]) == {"records", "files", "symbols", "downstream_callers"}


def test_impact_analysis_missing_target(tmp_path):
    from whyloom.retrieval import impact_analysis

    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    with GraphStore(root / DEFAULT_CONFIG["database"]) as store:
        result = impact_analysis(store, "does-not-exist-xyz")
    assert not result["found"]
    assert result["warnings"]
