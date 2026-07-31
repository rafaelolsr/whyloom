import shutil
from pathlib import Path

from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.mapview import build_map_payload, render_map_html
from whyloom.store import GraphStore

FIXTURE = Path(__file__).parent / "fixtures" / "sample_repo"


def _indexed_store(tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(FIXTURE, root)
    index_project(root, DEFAULT_CONFIG)
    return GraphStore(root / DEFAULT_CONFIG["database"])


def test_build_map_payload_summarizes_graph(tmp_path):
    with _indexed_store(tmp_path) as store:
        payload = build_map_payload(store)
    summary = payload["summary"]
    assert summary["total_nodes"] > 0
    assert summary["total_edges"] > 0
    assert payload["nodes"], "expected drawn nodes"
    # Accepted records are marked authoritative for the gold ring.
    assert any(node["authoritative"] for node in payload["nodes"])
    # Every drawn edge connects two drawn nodes.
    ids = {node["id"] for node in payload["nodes"]}
    for edge in payload["edges"]:
        assert edge["source"] in ids and edge["target"] in ids


def test_map_respects_max_nodes_and_keeps_records(tmp_path):
    with _indexed_store(tmp_path) as store:
        full = build_map_payload(store)
        payload = build_map_payload(store, max_nodes=3)
    assert len(payload["nodes"]) <= 3
    assert payload["summary"]["truncated_nodes"] >= 0
    # Governed records survive truncation because they sort first.
    record_types = {n["type"] for n in full["nodes"] if n["type"] in {"Decision", "Constraint"}}
    kept_types = {n["type"] for n in payload["nodes"]}
    assert record_types <= kept_types or not record_types


def test_render_map_html_is_standalone(tmp_path):
    with _indexed_store(tmp_path) as store:
        payload = build_map_payload(store)
    document = render_map_html(payload)
    assert document.startswith("<!doctype html>")
    assert "const DATA =" in document
    assert "<canvas" in document
    # Offline: no external network references.
    assert "http://" not in document
    assert "https://" not in document
    # No unrendered template placeholders leaked.
    for placeholder in ("{title}", "{data_json}", "{counts_rows}"):
        assert placeholder not in document
