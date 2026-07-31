from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Diagnostic, GraphEdge, GraphNode


@dataclass(frozen=True)
class PythonExtraction:
    path: str
    digest: str
    module: str
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    diagnostics: list[Diagnostic]


def source_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _qualname(stack: list[str], name: str) -> str:
    return ".".join([*stack, name])


def _module_name(relative: str) -> str:
    module = relative.removesuffix(".py").replace("/", ".")
    return module.removesuffix(".__init__")


def _expression_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _expression_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def searchable_text(value: str) -> str:
    pieces: list[str] = []
    current = ""
    for char in value:
        if char in "._-/:":
            if current:
                pieces.append(current)
                current = ""
            continue
        if current and char.isupper() and current[-1].islower():
            pieces.append(current)
            current = char
        else:
            current += char
    if current:
        pieces.append(current)
    return " ".join(dict.fromkeys([value, *pieces, *[piece.casefold() for piece in pieces]]))


def extract_python(path: Path, root: Path) -> PythonExtraction:
    rel = path.relative_to(root).as_posix()
    digest = source_hash(path)
    module = _module_name(rel)
    file_id = f"file:{rel}"
    file_data: dict[str, Any] = {"language": "python", "module": module, "imports": []}
    nodes: list[GraphNode] = [
        GraphNode(
            id=file_id,
            type="File",
            label=rel,
            path=rel,
            source_path=rel,
            source_hash=digest,
            data=file_data,
        )
    ]
    edges: list[GraphEdge] = []
    diagnostics: list[Diagnostic] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
    except (SyntaxError, UnicodeDecodeError) as exc:
        diagnostics.append(Diagnostic(code="PY001", severity="warning", message=str(exc), path=rel))
        return PythonExtraction(rel, digest, module, nodes, edges, diagnostics)

    stack: list[str] = []
    symbol_stack: list[str] = []
    bindings_stack: list[dict[str, str]] = []
    node_by_id: dict[str, GraphNode] = {file_id: nodes[0]}

    class Visitor(ast.NodeVisitor):
        def _symbol(self, node: ast.AST, name: str, kind: str) -> str:
            qualname = _qualname(stack, name)
            symbol_id = f"symbol:{rel}:{qualname}"
            parent_id = symbol_stack[-1] if symbol_stack else file_id
            symbol = GraphNode(
                id=symbol_id,
                type="Symbol",
                label=qualname,
                path=rel,
                source_path=rel,
                source_hash=digest,
                data={
                    "kind": kind,
                    "line": getattr(node, "lineno", None),
                    "end_line": getattr(node, "end_lineno", None),
                    "module": module,
                    "calls": [],
                    "bases": [],
                    "references": [],
                    "bindings": {},
                },
            )
            nodes.append(symbol)
            node_by_id[symbol_id] = symbol
            edges.append(
                GraphEdge(
                    source=parent_id,
                    target=symbol_id,
                    type="CONTAINS",
                    origin="python-ast",
                    provenance="EXTRACTED",
                    evidence=f"{rel}:{getattr(node, 'lineno', 1)}",
                    source_path=rel,
                    source_hash=digest,
                )
            )
            return symbol_id

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            symbol_id = self._symbol(node, node.name, "class")
            node_by_id[symbol_id].data["bases"] = [name for base in node.bases if (name := _expression_name(base))]
            stack.append(node.name)
            symbol_stack.append(symbol_id)
            bindings_stack.append({})
            self.generic_visit(node)
            bindings_stack.pop()
            symbol_stack.pop()
            stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            symbol_id = self._symbol(node, node.name, "method" if stack else "function")
            stack.append(node.name)
            symbol_stack.append(symbol_id)
            bindings_stack.append({})
            self.generic_visit(node)
            node_by_id[symbol_id].data["bindings"] = dict(sorted(bindings_stack[-1].items()))
            bindings_stack.pop()
            symbol_stack.pop()
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                file_data["imports"].append({"module": alias.name, "name": None, "alias": local, "line": node.lineno})
                target = f"module-ref:{rel}:{alias.name}"
                nodes.append(
                    GraphNode(
                        id=target,
                        type="Module",
                        label=alias.name,
                        source_path=rel,
                        source_hash=digest,
                        data={"external": True},
                    )
                )
                edges.append(
                    GraphEdge(
                        source=file_id,
                        target=target,
                        type="IMPORTS",
                        origin="python-ast",
                        provenance="EXTRACTED",
                        evidence=f"{rel}:{node.lineno}",
                        source_path=rel,
                        source_hash=digest,
                    )
                )

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if not node.module:
                return
            for alias in node.names:
                local = alias.asname or alias.name
                file_data["imports"].append(
                    {"module": node.module, "name": alias.name, "alias": local, "line": node.lineno, "level": node.level}
                )
            target = f"module-ref:{rel}:{node.module}"
            nodes.append(
                GraphNode(
                    id=target,
                    type="Module",
                    label=node.module,
                    source_path=rel,
                    source_hash=digest,
                    data={"external": True},
                )
            )
            edges.append(
                GraphEdge(
                    source=file_id,
                    target=target,
                    type="IMPORTS",
                    origin="python-ast",
                    provenance="EXTRACTED",
                    evidence=f"{rel}:{node.lineno}",
                    source_path=rel,
                    source_hash=digest,
                )
            )

        def visit_Assign(self, node: ast.Assign) -> None:
            if bindings_stack and isinstance(node.value, ast.Call):
                constructor = _expression_name(node.value.func)
                if constructor:
                    for target in node.targets:
                        target_name = _expression_name(target)
                        if target_name:
                            bindings_stack[-1][target_name] = constructor
            self.generic_visit(node)

        def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
            if bindings_stack:
                target_name = _expression_name(node.target)
                annotation = _expression_name(node.annotation)
                if target_name and annotation:
                    bindings_stack[-1][target_name] = annotation
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call) -> None:
            if symbol_stack:
                target = _expression_name(node.func)
                if target:
                    binding = None
                    receiver = target.rpartition(".")[0]
                    for scope_bindings in reversed(bindings_stack):
                        if receiver in scope_bindings:
                            binding = scope_bindings[receiver]
                            break
                    node_by_id[symbol_stack[-1]].data["calls"].append(
                        {"target": target, "line": node.lineno, "receiver_type": binding}
                    )
            self.generic_visit(node)

        def visit_Name(self, node: ast.Name) -> None:
            if symbol_stack and isinstance(node.ctx, ast.Load):
                node_by_id[symbol_stack[-1]].data["references"].append({"target": node.id, "line": node.lineno})

        def visit_Attribute(self, node: ast.Attribute) -> None:
            if symbol_stack and isinstance(node.ctx, ast.Load):
                target = _expression_name(node)
                if target:
                    node_by_id[symbol_stack[-1]].data["references"].append({"target": target, "line": node.lineno})
            self.generic_visit(node)

    Visitor().visit(tree)
    file_data["imports"] = sorted(file_data["imports"], key=lambda item: (item["line"], item["alias"]))
    for node in nodes:
        if node.type == "Symbol":
            node.data["calls"] = list({(item["target"], item["line"], item.get("receiver_type")): item for item in node.data["calls"]}.values())
            node.data["references"] = list({(item["target"], item["line"]): item for item in node.data["references"]}.values())
    unique_nodes = {node.id: node for node in nodes}
    return PythonExtraction(rel, digest, module, list(unique_nodes.values()), edges, diagnostics)


def _resolve_relative_module(current: str, module: str, level: int) -> str:
    if level <= 0:
        return module
    parts = current.split(".")[:-1]
    keep = max(0, len(parts) - level + 1)
    return ".".join([*parts[:keep], module] if module else parts[:keep])


def resolve_python_project(extractions: list[PythonExtraction]) -> list[GraphEdge]:
    module_files = {item.module: f"file:{item.path}" for item in extractions}
    symbols: dict[str, str] = {}
    file_symbols: dict[str, dict[str, str]] = {}
    class_bindings: dict[tuple[str, str], dict[str, str]] = {}
    for extraction in extractions:
        local: dict[str, str] = {}
        for node in extraction.nodes:
            if node.type != "Symbol":
                continue
            symbols[f"{extraction.module}.{node.label}"] = node.id
            local[node.label] = node.id
            local.setdefault(node.label.split(".")[-1], node.id)
            if node.data.get("kind") == "method" and "." in node.label:
                class_name = node.label.rsplit(".", 1)[0]
                bindings = class_bindings.setdefault((extraction.path, class_name), {})
                bindings.update({k: v for k, v in node.data.get("bindings", {}).items() if k.startswith("self.")})
        file_symbols[extraction.path] = local

    edges: list[GraphEdge] = []
    seen: set[tuple[str, str, str, str]] = set()

    def add(source: str, target: str | None, edge_type: str, extraction: PythonExtraction, line: int, confidence: float, provenance: str) -> None:
        if target is None or target == source:
            return
        evidence = f"{extraction.path}:{line}"
        key = (source, target, edge_type, evidence)
        if key in seen:
            return
        seen.add(key)
        edges.append(
            GraphEdge(
                source=source,
                target=target,
                type=edge_type,
                origin="python-project-resolver",
                provenance=provenance,
                evidence=evidence,
                confidence=confidence,
                source_path="@python-project",
                source_hash="",
            )
        )

    for extraction in extractions:
        file_node = f"file:{extraction.path}"
        file_data = next(node.data for node in extraction.nodes if node.id == file_node)
        imports: dict[str, tuple[str, str | None]] = {}
        for item in file_data.get("imports", []):
            module = _resolve_relative_module(extraction.module, item["module"], int(item.get("level", 0)))
            imports[item["alias"]] = (module, item.get("name"))
            add(file_node, module_files.get(module), "IMPORTS", extraction, item["line"], 1.0, "EXTRACTED")

        def imported_target(name: str) -> str | None:
            head, _, tail = name.partition(".")
            imported = imports.get(head)
            if imported is None:
                return None
            module, imported_name = imported
            suffix = ".".join(part for part in (imported_name, tail) if part)
            if suffix:
                return symbols.get(f"{module}.{suffix}")
            return module_files.get(module)

        local = file_symbols[extraction.path]
        for node in extraction.nodes:
            if node.type != "Symbol":
                continue
            class_name = node.label.rsplit(".", 1)[0] if node.data.get("kind") == "method" else ""
            bindings = {**class_bindings.get((extraction.path, class_name), {}), **node.data.get("bindings", {})}

            for base in node.data.get("bases", []):
                target = local.get(base) or imported_target(base)
                add(node.id, target, "INHERITS", extraction, node.data.get("line") or 1, 1.0, "EXTRACTED")

            for call in node.data.get("calls", []):
                name = call["target"]
                target: str | None = None
                provenance = "EXTRACTED"
                confidence = 1.0
                if name.startswith("self.") and class_name:
                    member = name.removeprefix("self.")
                    target = local.get(f"{class_name}.{member}")
                receiver = name.rpartition(".")[0]
                receiver_type = call.get("receiver_type") or bindings.get(receiver)
                if target is None and receiver_type:
                    method = name.rsplit(".", 1)[-1]
                    target = local.get(f"{receiver_type}.{method}") or imported_target(f"{receiver_type}.{method}")
                    provenance = "INFERRED"
                    confidence = 0.75
                if target is None:
                    target = local.get(name) or local.get(name.rsplit(".", 1)[-1]) or imported_target(name)
                add(node.id, target, "CALLS", extraction, call["line"], confidence, provenance)

            for reference in node.data.get("references", []):
                name = reference["target"]
                target = local.get(name) or imported_target(name)
                add(node.id, target, "REFERENCES", extraction, reference["line"], 0.8, "INFERRED")
    return edges
