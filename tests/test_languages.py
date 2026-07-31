from pathlib import Path
from unittest import mock

import pytest

import whyloom.languages as languages
from whyloom.config import DEFAULT_CONFIG
from whyloom.indexer import index_project
from whyloom.languages import AdapterRegistry, PythonAdapter, TreeSitterAdapter, default_registry
from whyloom.store import GraphStore

TS_SOURCE = """import { Store } from "./store";

export class TokenService {
  rotate(user: string) {
    return this.issue(user);
  }
  issue(user: string) {
    return { user };
  }
}

export function revokeAllSessions(user: string) {
  return true;
}
"""


def _grammar_available(suffix: str = ".ts") -> bool:
    grammar = languages.TREE_SITTER_GRAMMARS[suffix]
    return languages._load_parser(grammar) is not None


# (suffix, source, expected symbol names) for each Phase 2 language.
LANGUAGE_SAMPLES = [
    (".go", "package main\nfunc Rotate(u string) string { return u }\ntype Store struct{}\n", {"Rotate", "Store"}),
    (".rs", "pub fn rotate(u: &str) -> bool { true }\nstruct Token;\nenum Kind { A }\n", {"rotate", "Token", "Kind"}),
    (".java", "class TokenService {\n  String rotate(String u){ return u; }\n}\n", {"TokenService", "rotate"}),
    (".cs", "class TokenService {\n  string Rotate(string u){ return u; }\n}\n", {"TokenService", "Rotate"}),
]


@pytest.mark.parametrize("suffix, source, expected", LANGUAGE_SAMPLES)
def test_phase2_language_extraction(tmp_path, suffix, source, expected):
    if not _grammar_available(suffix):
        pytest.skip(f"tree-sitter grammar for {suffix} not installed")
    path = tmp_path / f"sample{suffix}"
    path.write_text(source, encoding="utf-8")
    extraction = TreeSitterAdapter().extract(path, tmp_path)
    names = {n.label for n in extraction.nodes if n.type == "Symbol"}
    assert expected <= names
    assert not any(d.severity == "error" for d in extraction.diagnostics)


def test_all_registered_suffixes_have_globs():
    from whyloom.config import DEFAULT_INCLUDE_PATTERNS

    globbed = {p.rsplit(".", 1)[-1] for p in DEFAULT_INCLUDE_PATTERNS if p.startswith("**/*.")}
    for suffix in languages.TREE_SITTER_GRAMMARS:
        assert suffix.lstrip(".") in globbed, f"{suffix} has no discovery glob"


def test_registry_dispatches_by_suffix():
    registry = default_registry()
    assert isinstance(registry.for_path(Path("a.py")), PythonAdapter)
    assert isinstance(registry.for_path(Path("a.ts")), TreeSitterAdapter)
    assert registry.for_path(Path("a.rb")) is None
    assert {".py", ".ts", ".tsx", ".js", ".jsx"} <= set(registry.code_suffixes)


def test_registry_first_adapter_wins_for_suffix():
    registry = AdapterRegistry()
    registry.register(PythonAdapter())
    registry.register(PythonAdapter())
    assert len(registry.adapters) == 2
    assert registry.code_suffixes == frozenset({".py"})


def test_tree_sitter_degrades_without_grammar(tmp_path):
    (tmp_path / "x.ts").write_text("export function foo() {}\n", encoding="utf-8")
    with mock.patch.object(languages, "_load_parser", return_value=None):
        extraction = TreeSitterAdapter().extract(tmp_path / "x.ts", tmp_path)
    assert [n.type for n in extraction.nodes] == ["File"]
    assert any(d.code == "LANG002" for d in extraction.diagnostics)


@pytest.mark.skipif(not _grammar_available(), reason="tree-sitter TypeScript grammar not installed")
def test_typescript_extraction_end_to_end(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "auth.ts").write_text(TS_SOURCE, encoding="utf-8")
    result = index_project(tmp_path, DEFAULT_CONFIG)
    assert result["indexed"]
    assert "src/auth.ts" in result["changed"]

    with GraphStore(tmp_path / ".whyloom" / "cache" / "graph.sqlite", create=False) as store:
        rows = store.connection.execute(
            "SELECT label FROM nodes WHERE source_path = 'src/auth.ts' AND type = 'Symbol' ORDER BY label"
        ).fetchall()
        symbols = {row["label"] for row in rows}
        # Methods nest under the class exactly like the Python adapter.
        contains = store.connection.execute(
            "SELECT target FROM edges WHERE source = 'symbol:src/auth.ts:TokenService' AND type = 'CONTAINS'"
        ).fetchall()
    assert {"TokenService", "rotate", "issue", "revokeAllSessions"} <= symbols
    method_ids = {row["target"] for row in contains}
    assert "symbol:src/auth.ts:rotate" in method_ids
    assert "symbol:src/auth.ts:issue" in method_ids
