import xml.dom.minidom as minidom

from whyloom.config import DEFAULT_CONFIG
from whyloom.exporters import export_graphml, export_svg
from whyloom.indexer import index_project
from whyloom.operations import init_project
from whyloom.report import build_report_data, render_report_markdown
from whyloom.store import GraphStore


def _indexed(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "auth.py").write_text(
        "def login(u):\n    # WHY: server-side tokens\n    return helper(u)\n\ndef helper(u):\n    return u\n",
        encoding="utf-8",
    )
    init_project(root)
    index_project(root, DEFAULT_CONFIG)
    return GraphStore(root / DEFAULT_CONFIG["database"], create=False)


def test_graphml_is_valid_xml(tmp_path):
    with _indexed(tmp_path) as store:
        doc = export_graphml(store)
    parsed = minidom.parseString(doc)  # raises if malformed
    assert parsed.getElementsByTagName("node")
    assert parsed.getElementsByTagName("graphml")


def test_svg_is_valid_and_bounded(tmp_path):
    with _indexed(tmp_path) as store:
        doc = export_svg(store, max_nodes=50)
    parsed = minidom.parseString(doc)
    assert parsed.documentElement.tagName == "svg"
    assert parsed.getElementsByTagName("circle")


def test_svg_layout_is_deterministic(tmp_path):
    with _indexed(tmp_path) as store:
        first = export_svg(store)
        second = export_svg(store)
    assert first == second  # seeded layout, no RNG


def test_report_finds_god_nodes_and_questions(tmp_path):
    with _indexed(tmp_path) as store:
        data = build_report_data(store)
    assert data["totals"]["nodes"] > 0
    assert data["god_nodes"]
    assert all("degree" in n for n in data["god_nodes"])
    assert data["suggested_questions"]
    markdown = render_report_markdown(data)
    assert "# Whyloom graph report" in markdown
    assert "Suggested questions" in markdown
