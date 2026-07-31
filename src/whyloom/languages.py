"""Language adapter registry.

Extraction is language-pluggable: every adapter turns one source file into the
same neutral ``GraphNode``/``GraphEdge`` shapes and optionally resolves
cross-file relationships within its own language. The Python adapter wraps the
deterministic ``ast`` extractor; the tree-sitter adapter covers additional
languages through per-grammar query tables so new languages are configuration,
not new code.

Tree-sitter grammars are optional dependencies. When a source file's grammar is
not installed the adapter emits a ``LANG002`` diagnostic and a bare ``File``
node rather than failing the index, keeping the base install small and offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .codegraph import PythonExtraction, extract_python, resolve_python_project, source_hash
from .models import Diagnostic, GraphEdge, GraphNode


@dataclass(frozen=True)
class Extraction:
    """Neutral result any adapter returns for a single source file."""

    path: str
    digest: str
    language: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    diagnostics: list[Diagnostic]
    payload: object | None = None  # adapter-private data for the resolve pass


class LanguageAdapter(Protocol):
    name: str
    suffixes: tuple[str, ...]

    def extract(self, path: Path, root: Path) -> Extraction: ...

    def resolve_project(self, extractions: list[Extraction]) -> list[GraphEdge]:
        """Cross-file edges within this language. Default: none."""
        ...


class PythonAdapter:
    name = "python"
    suffixes = (".py",)

    def extract(self, path: Path, root: Path) -> Extraction:
        result: PythonExtraction = extract_python(path, root)
        return Extraction(
            path=result.path,
            digest=result.digest,
            language="python",
            nodes=result.nodes,
            edges=result.edges,
            diagnostics=result.diagnostics,
            payload=result,
        )

    def resolve_project(self, extractions: list[Extraction]) -> list[GraphEdge]:
        payloads = [e.payload for e in extractions if isinstance(e.payload, PythonExtraction)]
        return resolve_python_project(payloads)


@dataclass(frozen=True)
class TreeSitterGrammar:
    """Per-language wiring for the generic tree-sitter adapter.

    ``module`` is the pip-installed grammar package; ``symbol_nodes`` maps
    tree-sitter node types to Whyloom symbol kinds; ``import_nodes`` names node
    types whose text is recorded as an import. Adding a Phase 2 language is a new
    entry here plus an optional-dependency extra."""

    language: str
    module: str
    symbol_nodes: dict[str, str]
    import_nodes: tuple[str, ...] = ()
    name_fields: tuple[str, ...] = ("name",)


# Phase 1 ships TypeScript/JavaScript; Phase 2 languages slot in as more rows.
TREE_SITTER_GRAMMARS: dict[str, TreeSitterGrammar] = {
    ".ts": TreeSitterGrammar(
        "typescript",
        "tree_sitter_typescript",
        {
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        import_nodes=("import_statement",),
    ),
    ".tsx": TreeSitterGrammar(
        "typescript",
        "tree_sitter_typescript",
        {
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        import_nodes=("import_statement",),
    ),
    ".js": TreeSitterGrammar(
        "javascript",
        "tree_sitter_javascript",
        {
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        import_nodes=("import_statement",),
    ),
    ".jsx": TreeSitterGrammar(
        "javascript",
        "tree_sitter_javascript",
        {
            "function_declaration": "function",
            "method_definition": "method",
            "class_declaration": "class",
        },
        import_nodes=("import_statement",),
    ),
    ".go": TreeSitterGrammar(
        "go",
        "tree_sitter_go",
        {
            "function_declaration": "function",
            "method_declaration": "method",
            "type_spec": "type",  # inner spec carries the name; type_declaration does not
        },
        import_nodes=("import_declaration",),
    ),
    ".rs": TreeSitterGrammar(
        "rust",
        "tree_sitter_rust",
        {
            "function_item": "function",
            "struct_item": "struct",
            "enum_item": "enum",
            "trait_item": "trait",
            # impl_item is intentionally excluded: it has no name field, it
            # references a type. Emitting it would produce nameless symbols.
        },
        import_nodes=("use_declaration",),
    ),
    ".java": TreeSitterGrammar(
        "java",
        "tree_sitter_java",
        {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "method_declaration": "method",
            "constructor_declaration": "constructor",
        },
        import_nodes=("import_declaration",),
    ),
    ".cs": TreeSitterGrammar(
        "c_sharp",
        "tree_sitter_c_sharp",
        {
            "class_declaration": "class",
            "interface_declaration": "interface",
            "struct_declaration": "struct",
            "method_declaration": "method",
        },
        import_nodes=("using_directive",),
    ),
}


def _load_parser(grammar: TreeSitterGrammar):
    """Return a tree-sitter Parser for the grammar, or None if unavailable.

    Import is lazy so the base install never requires tree-sitter."""
    try:
        import importlib

        import tree_sitter

        module = importlib.import_module(grammar.module)
        # typescript packages expose language_typescript()/language_tsx();
        # single-language packages expose language().
        getter = None
        for candidate in (f"language_{grammar.language}", "language_typescript", "language"):
            getter = getattr(module, candidate, None)
            if getter is not None:
                break
        if getter is None:
            return None
        language = tree_sitter.Language(getter())
        return tree_sitter.Parser(language)
    except Exception:
        return None


class TreeSitterAdapter:
    """Generic AST adapter driven by :class:`TreeSitterGrammar` tables."""

    name = "tree-sitter"

    @property
    def suffixes(self) -> tuple[str, ...]:
        return tuple(TREE_SITTER_GRAMMARS)

    def extract(self, path: Path, root: Path) -> Extraction:
        rel = path.relative_to(root).as_posix()
        digest = source_hash(path)
        grammar = TREE_SITTER_GRAMMARS[path.suffix.casefold()]
        file_id = f"file:{rel}"
        nodes = [
            GraphNode(
                id=file_id,
                type="File",
                label=rel,
                path=rel,
                source_path=rel,
                source_hash=digest,
                data={"language": grammar.language, "imports": []},
            )
        ]
        edges: list[GraphEdge] = []
        diagnostics: list[Diagnostic] = []

        parser = _load_parser(grammar)
        if parser is None:
            diagnostics.append(
                Diagnostic(
                    code="LANG002",
                    severity="warning",
                    message=f"tree-sitter grammar for {grammar.language} not installed; "
                    f"install whyloom[{grammar.language}] for symbol extraction",
                    path=rel,
                )
            )
            return Extraction(rel, digest, grammar.language, nodes, edges, diagnostics)

        try:
            source = path.read_bytes()
            tree = parser.parse(source)
        except Exception as exc:  # pragma: no cover - defensive
            diagnostics.append(Diagnostic(code="TS001", severity="warning", message=str(exc), path=rel))
            return Extraction(rel, digest, grammar.language, nodes, edges, diagnostics)

        imports: list[str] = []
        self._walk(tree.root_node, source, grammar, rel, digest, file_id, nodes, edges, imports)
        nodes[0].data["imports"] = imports
        return Extraction(rel, digest, grammar.language, nodes, edges, diagnostics)

    def _walk(self, node, source, grammar, rel, digest, file_id, nodes, edges, imports, parent_id=None):
        parent_id = parent_id or file_id
        current_parent = parent_id
        node_type = node.type
        if node_type in grammar.symbol_nodes:
            name = self._name(node, source, grammar)
            if name:
                symbol_id = f"symbol:{rel}:{name}"
                line = node.start_point[0] + 1
                nodes.append(
                    GraphNode(
                        id=symbol_id,
                        type="Symbol",
                        label=name,
                        path=rel,
                        source_path=rel,
                        source_hash=digest,
                        data={
                            "kind": grammar.symbol_nodes[node_type],
                            "line": line,
                            "end_line": node.end_point[0] + 1,
                            "calls": [],
                            "bases": [],
                            "references": [],
                        },
                    )
                )
                edges.append(
                    GraphEdge(
                        source=parent_id,
                        target=symbol_id,
                        type="CONTAINS",
                        origin="tree-sitter",
                        provenance="EXTRACTED",
                        evidence=f"{rel}:{line}",
                        source_path=rel,
                        source_hash=digest,
                    )
                )
                current_parent = symbol_id
        elif node_type in grammar.import_nodes:
            text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
            imports.append(" ".join(text.split()))
        for child in node.children:
            self._walk(child, source, grammar, rel, digest, file_id, nodes, edges, imports, current_parent)

    @staticmethod
    def _name(node, source, grammar) -> str | None:
        for field_name in grammar.name_fields:
            child = node.child_by_field_name(field_name)
            if child is not None:
                return source[child.start_byte : child.end_byte].decode("utf-8", "replace")
        return None

    def resolve_project(self, extractions: list[Extraction]) -> list[GraphEdge]:
        # Within-language cross-file resolution is Phase 3; none for now.
        return []


@dataclass
class AdapterRegistry:
    adapters: list[LanguageAdapter] = field(default_factory=list)
    _by_suffix: dict[str, LanguageAdapter] = field(default_factory=dict)

    def register(self, adapter: LanguageAdapter) -> None:
        self.adapters.append(adapter)
        for suffix in adapter.suffixes:
            self._by_suffix.setdefault(suffix, adapter)

    def for_path(self, path: Path) -> LanguageAdapter | None:
        return self._by_suffix.get(path.suffix.casefold())

    @property
    def code_suffixes(self) -> frozenset[str]:
        return frozenset(self._by_suffix)


def default_registry() -> AdapterRegistry:
    registry = AdapterRegistry()
    registry.register(PythonAdapter())
    registry.register(TreeSitterAdapter())
    return registry


CODE_SUFFIXES: frozenset[str] = default_registry().code_suffixes
