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
    # Node types whose leading identifier names a called symbol, and node types
    # that name a base type. These drive within-language cross-file resolution.
    call_nodes: tuple[str, ...] = ()
    inherit_nodes: tuple[str, ...] = ()


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
        call_nodes=("call_expression",),
        inherit_nodes=("extends_clause",),
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
        call_nodes=("call_expression",),
        inherit_nodes=("extends_clause",),
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
        call_nodes=("call_expression",),
        inherit_nodes=("extends_clause",),
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
        call_nodes=("call_expression",),
        inherit_nodes=("extends_clause",),
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
        call_nodes=("call_expression",),
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
        call_nodes=("call_expression",),
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
        call_nodes=("method_invocation",),
        inherit_nodes=("superclass",),
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
        call_nodes=("invocation_expression",),
        inherit_nodes=("base_list",),
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
        node_by_id: dict[str, GraphNode] = {file_id: nodes[0]}
        self._walk(tree.root_node, source, grammar, rel, digest, file_id, nodes, edges, imports, node_by_id)
        nodes[0].data["imports"] = imports
        return Extraction(rel, digest, grammar.language, nodes, edges, diagnostics)

    def _walk(self, node, source, grammar, rel, digest, file_id, nodes, edges, imports, node_by_id, parent_id=None):
        parent_id = parent_id or file_id
        current_parent = parent_id
        node_type = node.type
        if node_type in grammar.symbol_nodes:
            name = self._name(node, source, grammar)
            if name:
                symbol_id = f"symbol:{rel}:{name}"
                line = node.start_point[0] + 1
                symbol = GraphNode(
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
                nodes.append(symbol)
                node_by_id[symbol_id] = symbol
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
                # Base types declared on this symbol (extends / superclass / base_list).
                # The clause may be nested (e.g. class_heritage > extends_clause),
                # so search descendants but stop before the symbol's own body.
                for inherit_node in self._find_inherit_nodes(node, grammar):
                    for base in self._identifiers(inherit_node, source):
                        symbol.data["bases"].append(base)
        elif node_type in grammar.import_nodes:
            text = source[node.start_byte : node.end_byte].decode("utf-8", "replace")
            imports.append(" ".join(text.split()))
        elif node_type in grammar.call_nodes and current_parent in node_by_id:
            callee = self._call_target(node, source)
            if callee:
                node_by_id[current_parent].data["calls"].append(
                    {"target": callee, "line": node.start_point[0] + 1}
                )
        for child in node.children:
            self._walk(child, source, grammar, rel, digest, file_id, nodes, edges, imports, node_by_id, current_parent)

    @staticmethod
    def _name(node, source, grammar) -> str | None:
        for field_name in grammar.name_fields:
            child = node.child_by_field_name(field_name)
            if child is not None:
                return source[child.start_byte : child.end_byte].decode("utf-8", "replace")
        return None

    @staticmethod
    def _call_target(node, source) -> str | None:
        """Return the callee identifier of a call node, taking the final name of
        a member access (``a.b.c`` -> ``c``) to match by symbol name."""
        function = node.child_by_field_name("function") or (node.children[0] if node.children else None)
        if function is None:
            return None
        text = source[function.start_byte : function.end_byte].decode("utf-8", "replace")
        return text.split(".")[-1].split("::")[-1].strip() or None

    @staticmethod
    def _find_inherit_nodes(symbol_node, grammar) -> list:
        """Find inheritance-clause nodes for a symbol, descending through wrapper
        nodes (class_heritage) but never into a nested body/block."""
        found = []

        def visit(current):
            if current.type in grammar.inherit_nodes:
                found.append(current)
                return
            if current.type.endswith(("_body", "block", "declaration_list")):
                return
            for child in current.children:
                visit(child)

        for child in symbol_node.children:
            visit(child)
        return found

    @staticmethod
    def _identifiers(node, source) -> list[str]:
        """Collect bare type identifiers under an inheritance node."""
        found: list[str] = []

        def visit(current):
            if current.type in {"type_identifier", "identifier"} and current.child_count == 0:
                found.append(source[current.start_byte : current.end_byte].decode("utf-8", "replace"))
            for child in current.children:
                visit(child)

        visit(node)
        return found

    def resolve_project(self, extractions: list[Extraction]) -> list[GraphEdge]:
        """Within-language cross-file resolution by symbol name.

        Calls and base types are linked to same-language symbols with matching
        names. Because grammar-level extraction does not track import aliases,
        matches are INFERRED and lose confidence when a name is ambiguous across
        files. Whyloom's provenance model surfaces exactly this uncertainty."""
        by_name: dict[str, list[str]] = {}
        for extraction in extractions:
            for node in extraction.nodes:
                if node.type == "Symbol":
                    by_name.setdefault(node.label, []).append(node.id)

        edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str, str]] = set()

        def link(source_id: str, name: str, edge_type: str, path: str, line: int) -> None:
            targets = by_name.get(name)
            if not targets:
                return
            # Prefer a target in another file; skip pure self-references.
            candidates = [t for t in targets if t != source_id] or targets
            if not candidates:
                return
            target = candidates[0]
            confidence = 0.9 if len(candidates) == 1 else round(1.0 / len(candidates), 2)
            evidence = f"{path}:{line}"
            key = (source_id, target, edge_type, evidence)
            if key in seen:
                return
            seen.add(key)
            edges.append(
                GraphEdge(
                    source=source_id,
                    target=target,
                    type=edge_type,
                    origin="tree-sitter-project-resolver",
                    provenance="INFERRED",
                    evidence=evidence,
                    confidence=confidence,
                    source_path="@tree-sitter-project",
                    source_hash="",
                )
            )

        for extraction in extractions:
            for node in extraction.nodes:
                if node.type != "Symbol":
                    continue
                for call in node.data.get("calls", []):
                    link(node.id, call["target"], "CALLS", extraction.path, call.get("line", node.data.get("line", 1)))
                for base in node.data.get("bases", []):
                    link(node.id, base, "INHERITS", extraction.path, node.data.get("line", 1))
        return edges


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
