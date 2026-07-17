from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path

from .migrations import apply_migrations
from .models import GraphEdge, GraphNode

QUERY_STOPWORDS = {
    "affected",
    "change",
    "does",
    "explain",
    "exists",
    "from",
    "into",
    "that",
    "the",
    "this",
    "what",
    "why",
    "without",
}


class GraphStore:
    def __init__(self, path: Path, *, create: bool = True):
        self.path = path
        if not create and not path.is_file():
            raise FileNotFoundError(f"Whyloom index not found at {path}; run 'whyloom index' first")
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout = 30000")
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.execute("PRAGMA synchronous = NORMAL")
        apply_migrations(self.connection)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> GraphStore:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        try:
            yield
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise

    def source_hash(self, path: str) -> str | None:
        row = self.connection.execute("SELECT hash FROM sources WHERE path = ?", (path,)).fetchone()
        return row["hash"] if row else None

    def source_index_version(self, path: str) -> int | None:
        row = self.connection.execute("SELECT index_version FROM sources WHERE path = ?", (path,)).fetchone()
        return int(row["index_version"]) if row else None

    def outdated_source_count(self, index_version: int) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM sources WHERE index_version != ?", (index_version,)).fetchone()
        return int(row[0])

    def replace_source(
        self,
        path: str,
        digest: str,
        kind: str,
        index_version: int,
        nodes: Iterable[GraphNode],
        edges: Iterable[GraphEdge],
        documents: Iterable[tuple[str, str, str, str]],
    ) -> None:
        self.connection.execute("DELETE FROM documents WHERE node_id IN (SELECT id FROM nodes WHERE source_path = ?)", (path,))
        self.connection.execute("DELETE FROM edges WHERE source_path = ?", (path,))
        self.connection.execute("DELETE FROM nodes WHERE source_path = ?", (path,))
        for node in nodes:
            self.connection.execute(
                "INSERT OR REPLACE INTO nodes(id,type,label,path,source_path,source_hash,data) VALUES (?,?,?,?,?,?,?)",
                (node.id, node.type, node.label, node.path, node.source_path, node.source_hash, json.dumps(node.data, sort_keys=True)),
            )
        for edge in edges:
            self.connection.execute(
                "INSERT OR REPLACE INTO edges(source,target,type,origin,evidence,confidence,source_path,source_hash) VALUES (?,?,?,?,?,?,?,?)",
                (edge.source, edge.target, edge.type, edge.origin, edge.evidence, edge.confidence, edge.source_path, edge.source_hash),
            )
        for document in documents:
            self.connection.execute("INSERT INTO documents(node_id,label,body,path) VALUES (?,?,?,?)", document)
        self.connection.execute(
            "INSERT OR REPLACE INTO sources(path,hash,kind,index_version,indexed_at) VALUES (?,?,?,?,CURRENT_TIMESTAMP)",
            (path, digest, kind, index_version),
        )

    def remove_missing_sources(self, present: set[str]) -> list[str]:
        existing = {row["path"] for row in self.connection.execute("SELECT path FROM sources")}
        removed = sorted(existing - present)
        for path in removed:
            self.connection.execute("DELETE FROM documents WHERE node_id IN (SELECT id FROM nodes WHERE source_path = ?)", (path,))
            self.connection.execute("DELETE FROM edges WHERE source_path = ?", (path,))
            self.connection.execute("DELETE FROM nodes WHERE source_path = ?", (path,))
            self.connection.execute("DELETE FROM sources WHERE path = ?", (path,))
        return removed

    def node(self, identifier: str) -> dict | None:
        row = self.connection.execute(
            "SELECT * FROM nodes WHERE id = ? OR path = ? ORDER BY type = 'File' DESC LIMIT 1",
            (identifier, identifier),
        ).fetchone()
        return self._node_dict(row) if row else None

    def search(self, query: str, limit: int = 20) -> list[dict]:
        terms = re.findall(r"[a-zA-Z0-9_-]+", query.casefold())
        terms = [term for term in terms if len(term) > 1 and term not in QUERY_STOPWORDS]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"' for term in terms)
        try:
            rows = self.connection.execute(
                "SELECT n.*, bm25(documents) AS lexical_rank FROM documents JOIN nodes n ON n.id = documents.node_id WHERE documents MATCH ? ORDER BY lexical_rank LIMIT ?",
                (fts_query, limit),
            ).fetchall()
        except sqlite3.OperationalError:
            pattern = f"%{query}%"
            rows = self.connection.execute(
                "SELECT *, 0.0 AS lexical_rank FROM nodes WHERE label LIKE ? OR data LIKE ? LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        return [self._node_dict(row) | {"lexical_rank": row["lexical_rank"]} for row in rows]

    def neighbors(self, node_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT e.*, n.id AS n_id, n.type AS n_type, n.label AS n_label, n.path AS n_path, n.source_path AS n_source_path, n.source_hash AS n_source_hash, n.data AS n_data FROM edges e JOIN nodes n ON n.id = CASE WHEN e.source = ? THEN e.target ELSE e.source END WHERE e.source = ? OR e.target = ?",
            (node_id, node_id, node_id),
        ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "edge": {key: row[key] for key in ("source", "target", "type", "origin", "evidence", "confidence")},
                    "node": {
                        "id": row["n_id"],
                        "type": row["n_type"],
                        "label": row["n_label"],
                        "path": row["n_path"],
                        "source_path": row["n_source_path"],
                        "source_hash": row["n_source_hash"],
                        "data": json.loads(row["n_data"]),
                    },
                }
            )
        return result

    @staticmethod
    def _node_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "type": row["type"],
            "label": row["label"],
            "path": row["path"],
            "source_path": row["source_path"],
            "source_hash": row["source_hash"],
            "data": json.loads(row["data"]),
        }
