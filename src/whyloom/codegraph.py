from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from .models import Diagnostic, GraphEdge, GraphNode


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qualname(stack: list[str], name: str) -> str:
    return ".".join([*stack, name])


def extract_python(path: Path, root: Path) -> tuple[list[GraphNode], list[GraphEdge], list[Diagnostic]]:
    rel = path.relative_to(root).as_posix()
    digest = source_hash(path)
    file_id = f"file:{rel}"
    nodes = [
        GraphNode(
            id=file_id,
            type="File",
            label=rel,
            path=rel,
            source_path=rel,
            source_hash=digest,
            data={"language": "python"},
        )
    ]
    edges: list[GraphEdge] = []
    diagnostics: list[Diagnostic] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        diagnostics.append(Diagnostic(code="PY001", severity="warning", message=str(exc), path=rel))
        return nodes, edges, diagnostics

    stack: list[str] = []

    class Visitor(ast.NodeVisitor):
        def _symbol(self, node: ast.AST, name: str, kind: str) -> None:
            qualname = _qualname(stack, name)
            symbol_id = f"symbol:{rel}:{qualname}"
            nodes.append(
                GraphNode(
                    id=symbol_id,
                    type="Symbol",
                    label=qualname,
                    path=rel,
                    source_path=rel,
                    source_hash=digest,
                    data={"kind": kind, "line": getattr(node, "lineno", None)},
                )
            )
            edges.append(
                GraphEdge(
                    source=file_id,
                    target=symbol_id,
                    type="CONTAINS",
                    origin="python-ast",
                    evidence=f"{rel}:{getattr(node, 'lineno', 1)}",
                    source_path=rel,
                    source_hash=digest,
                )
            )

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            self._symbol(node, node.name, "class")
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            self._symbol(node, node.name, "function")
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                target = f"module:{rel}:{alias.name}"
                nodes.append(
                    GraphNode(
                        id=target,
                        type="Module",
                        label=alias.name,
                        source_path=rel,
                        source_hash=digest,
                    )
                )
                edges.append(
                    GraphEdge(
                        source=file_id,
                        target=target,
                        type="IMPORTS",
                        origin="python-ast",
                        evidence=f"{rel}:{node.lineno}",
                        source_path=rel,
                        source_hash=digest,
                    )
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module:
                target = f"module:{rel}:{node.module}"
                nodes.append(GraphNode(id=target, type="Module", label=node.module, source_path=rel, source_hash=digest))
                edges.append(
                    GraphEdge(
                        source=file_id,
                        target=target,
                        type="IMPORTS",
                        origin="python-ast",
                        evidence=f"{rel}:{node.lineno}",
                        source_path=rel,
                        source_hash=digest,
                    )
                )

    Visitor().visit(tree)
    unique_nodes = {node.id: node for node in nodes}
    return list(unique_nodes.values()), edges, diagnostics
