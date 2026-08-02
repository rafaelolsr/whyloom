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

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Protocol

from .codegraph import PythonExtraction, extract_python, resolve_python_project, source_hash
from .models import Diagnostic, GraphEdge, GraphNode

# Tagged rationale comments become first-class, queryable Rationale nodes.
# The comment is EXTRACTED (it literally exists) but its content is advisory:
# it never outranks an accepted Decision or Constraint record.
RATIONALE_TAGS = ("WHY", "HACK", "NOTE", "TODO", "FIXME", "XXX", "BUG", "WARNING", "OPTIMIZE")
_TAG_BODY = re.compile(
    r"(?:#|//|/\*|\*|<!--|--)\s*(" + "|".join(RATIONALE_TAGS) + r")\b[:\-\s]*(.+?)\s*(?:\*/|-->)?\s*$",
    re.IGNORECASE,
)
# A line-comment must start at line beginning or after code, and crucially the
# marker must not sit inside a string literal. We approximate that cheaply by
# rejecting lines where an odd number of quotes precede the marker.
_LINE_COMMENT = re.compile(r"^(?P<pre>[^\n]*?)(?P<marker>#|//|/\*|<!--|--)\s*(?P<rest>.*)$")


def _looks_like_string_context(prefix: str) -> bool:
    """True when the comment marker is likely inside a string literal, judged by
    an unbalanced count of unescaped quotes before it."""
    return (prefix.count('"') - prefix.count('\\"')) % 2 == 1 or (prefix.count("'") - prefix.count("\\'")) % 2 == 1


_ES_IMPORT_FROM = re.compile(r"import\s+(?P<clause>.+?)\s+from\s+['\"](?P<spec>[^'\"]+)['\"]")
_ES_NAMED = re.compile(r"\{([^}]*)\}")


def _parse_es_import(text: str) -> list[tuple[str, str]]:
    """Parse an ES/TS import into (local_name, module_specifier) pairs.

    Handles named (`import { a, b as c }`), default (`import D`), and namespace
    (`import * as ns`) forms. Only ES-style imports resolve to a file specifier;
    other languages' package imports are left to name-based resolution."""
    match = _ES_IMPORT_FROM.search(text)
    if not match:
        return []
    spec = match.group("spec")
    clause = match.group("clause").strip()
    names: list[str] = []
    named = _ES_NAMED.search(clause)
    if named:
        for part in named.group(1).split(","):
            piece = part.strip()
            if not piece:
                continue
            # `original as local` — the local name is what the file references.
            local = piece.split(" as ")[-1].strip()
            if local:
                names.append(local)
        clause = _ES_NAMED.sub("", clause)
    for token in clause.replace(",", " ").split():
        if token in {"*", "as", "import", "type"}:
            continue
        names.append(token.strip())
    return [(name, spec) for name in dict.fromkeys(names) if name]


def _resolve_relative_specifier(specifier: str, importer_rel: str) -> str | None:
    """Resolve a relative ES module specifier to a repo-relative source path,
    trying common TS/JS extensions and index files. Returns None for bare
    (package) specifiers, which do not map to a file in this repo."""
    if not specifier.startswith("."):
        return None
    base = PurePosixPath(importer_rel).parent
    target = base
    for part in specifier.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            target = target.parent
        else:
            target = target / part
    stem = target.as_posix()
    return stem  # candidate stem; the resolver matches it against known files.


def extract_rationale(
    text: str,
    rel: str,
    digest: str,
    symbol_ranges: list[tuple[int, int, str]],
) -> tuple[list[GraphNode], list[GraphEdge]]:
    """Turn tagged comments (WHY/HACK/NOTE/TODO/...) into Rationale nodes linked
    to the enclosing symbol, or the file when no symbol contains the line.

    ``symbol_ranges`` is (start_line, end_line, symbol_id); the innermost range
    containing a comment line wins so rationale attaches to the tightest scope."""
    file_id = f"file:{rel}"
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        comment = _LINE_COMMENT.match(line)
        # Reject markers that sit inside a string literal (test data, examples).
        if not comment or _looks_like_string_context(comment.group("pre")):
            continue
        match = _TAG_BODY.search(comment.group("marker") + " " + comment.group("rest"))
        if not match:
            continue
        tag = match.group(1).upper()
        note = match.group(2).strip()
        if not note:
            continue
        rationale_id = f"rationale:{rel}:{line_number}"
        # Tightest enclosing symbol: smallest span covering this line.
        target = file_id
        best_span = None
        for start, end, symbol_id in symbol_ranges:
            if start <= line_number <= end:
                span = end - start
                if best_span is None or span < best_span:
                    best_span = span
                    target = symbol_id
        nodes.append(
            GraphNode(
                id=rationale_id,
                type="Rationale",
                label=f"{tag}: {note[:80]}",
                path=rel,
                source_path=rel,
                source_hash=digest,
                data={"tag": tag, "note": note, "line": line_number},
            )
        )
        edges.append(
            GraphEdge(
                source=rationale_id,
                target=target,
                type="ANNOTATES",
                origin="rationale-comment",
                provenance="EXTRACTED",
                evidence=f"{rel}:{line_number}",
                confidence=1.0,
                source_path=rel,
                source_hash=digest,
            )
        )
    return nodes, edges


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
        # Read the file once; reuse the bytes for hashing, parsing, and rationale.
        try:
            content = path.read_bytes()
        except OSError:
            content = b""
        result: PythonExtraction = extract_python(path, root, content=content)
        nodes = list(result.nodes)
        edges = list(result.edges)
        symbol_ranges = [
            (node.data["line"], node.data.get("end_line") or node.data["line"], node.id)
            for node in result.nodes
            if node.type == "Symbol" and node.data.get("line")
        ]
        text = content.decode("utf-8", "replace")
        rationale_nodes, rationale_edges = extract_rationale(text, result.path, result.digest, symbol_ranges)
        nodes.extend(rationale_nodes)
        edges.extend(rationale_edges)
        return Extraction(
            path=result.path,
            digest=result.digest,
            language="python",
            nodes=nodes,
            edges=edges,
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
        self._alias_sink: list[tuple[str, str, str]] = []
        node_by_id: dict[str, GraphNode] = {file_id: nodes[0]}
        self._walk(tree.root_node, source, grammar, rel, digest, file_id, nodes, edges, imports, node_by_id)
        nodes[0].data["imports"] = imports
        # local_name -> candidate module stem (relative ES imports only).
        aliases: dict[str, str] = {}
        for name, specifier, importer_rel in self._alias_sink:
            stem = _resolve_relative_specifier(specifier, importer_rel)
            if stem is not None:
                aliases[name] = stem
        nodes[0].data["import_aliases"] = aliases

        symbol_ranges = [
            (node.data["line"], node.data.get("end_line", node.data["line"]), node.id)
            for node in nodes
            if node.type == "Symbol"
        ]
        rationale_nodes, rationale_edges = extract_rationale(
            source.decode("utf-8", "replace"), rel, digest, symbol_ranges
        )
        nodes.extend(rationale_nodes)
        edges.extend(rationale_edges)
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
            for name, specifier in _parse_es_import(text):
                self._alias_sink.append((name, specifier, rel))
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
        # (file_stem, symbol_name) -> symbol_id, for import-alias resolution.
        by_file_name: dict[tuple[str, str], str] = {}
        # Aliases declared per importing file: {importer_rel: {local_name: stem}}.
        aliases_by_file: dict[str, dict[str, str]] = {}
        known_stems: set[str] = set()
        for extraction in extractions:
            stem = extraction.path.rsplit(".", 1)[0]
            known_stems.add(stem)
            for node in extraction.nodes:
                if node.type == "Symbol":
                    by_name.setdefault(node.label, []).append(node.id)
                    by_file_name[(stem, node.label)] = node.id
                elif node.type == "File":
                    aliases = node.data.get("import_aliases") or {}
                    if aliases:
                        aliases_by_file[extraction.path] = aliases

        edges: list[GraphEdge] = []
        seen: set[tuple[str, str, str, str]] = set()

        def emit(source_id: str, target: str, edge_type: str, path: str, line: int, provenance: str, confidence: float) -> None:
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
                    provenance=provenance,
                    evidence=evidence,
                    confidence=confidence,
                    source_path="@tree-sitter-project",
                    source_hash="",
                )
            )

        def link(source_id: str, name: str, edge_type: str, importer: str, line: int) -> None:
            # Import-aliased resolution: the name was imported from a specific
            # file, so the target is unambiguous — EXTRACTED, confidence 1.0.
            alias_stem = aliases_by_file.get(importer, {}).get(name)
            if alias_stem is not None and alias_stem in known_stems:
                target = by_file_name.get((alias_stem, name))
                if target and target != source_id:
                    emit(source_id, target, edge_type, importer, line, "EXTRACTED", 1.0)
                    return
            # Fall back to name-based resolution — INFERRED, ambiguity lowers it.
            targets = by_name.get(name)
            if not targets:
                return
            candidates = [t for t in targets if t != source_id] or targets
            if not candidates:
                return
            confidence = 0.9 if len(candidates) == 1 else round(1.0 / len(candidates), 2)
            emit(source_id, candidates[0], edge_type, importer, line, "INFERRED", confidence)

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
