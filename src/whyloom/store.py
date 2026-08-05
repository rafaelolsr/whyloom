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


class CorruptIndexError(RuntimeError):
    """Raised when the SQLite index cannot be opened because it is malformed."""


def _query_terms(query: str) -> list[str]:
    expanded = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", query).replace("_", "-")
    terms = re.findall(r"[a-zA-Z0-9]+", expanded.casefold())
    return list(dict.fromkeys(term for term in terms if len(term) > 1 and term not in QUERY_STOPWORDS))


def _rerank_by_term_coverage(results: list[dict], terms: list[str]) -> list[dict]:
    """Re-rank FTS candidates so a node matching MORE distinct query terms in its
    identity (path + label) outranks one that merely repeats a single term. Raw
    bm25 rewards term frequency, which lets a file that says "ingestion" ten times
    beat `catalog/orchestrator/pipeline.py` on the query "catalog ingestion
    pipeline". Coverage of distinct terms in the name/path is the stronger signal
    for code retrieval; bm25 stays the tie-breaker within the same coverage."""
    if not terms:
        return results
    term_set = list(dict.fromkeys(terms))

    def coverage(item: dict) -> int:
        identity = f"{item.get('path') or ''} {item.get('label') or ''}"
        identity = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", identity).replace("_", "-").replace("/", " ").casefold()
        tokens = set(re.findall(r"[a-z0-9]+", identity))
        return sum(1 for term in term_set if term in tokens)

    # Sort by (most terms covered, then best bm25). Stable, fully deterministic.
    ranked = sorted(results, key=lambda item: (-coverage(item), item.get("lexical_rank", 0.0)))
    return _diversify_by_file(ranked)


def _diversify_by_file(ranked: list[dict], per_file_cap: int = 3) -> list[dict]:
    """Prevent one file from monopolizing the results. A file with many matching
    symbols (e.g. conversation_store.py) otherwise fills every slot, burying an
    equally relevant file (state/store.py) that has fewer symbols. Emit up to
    per_file_cap results per file in ranked order, then a second pass for the
    overflow — so distinct files surface before deep symbol lists. Deterministic:
    preserves relative order within each file."""
    def file_of(item: dict) -> str:
        return item.get("path") or item.get("source_path") or item.get("label", "")

    seen: dict[str, int] = {}
    kept: list[dict] = []
    overflow: list[dict] = []
    for item in ranked:
        key = file_of(item)
        seen[key] = seen.get(key, 0) + 1
        (kept if seen[key] <= per_file_cap else overflow).append(item)
    return kept + overflow


class GraphStore:
    def __init__(self, path: Path, *, create: bool = True):
        self.path = path
        if not create and not path.is_file():
            raise FileNotFoundError(f"Whyloom index not found at {path}; run 'whyloom index' first")
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, timeout=30)
        self.connection.row_factory = sqlite3.Row
        try:
            self.connection.execute("PRAGMA busy_timeout = 30000")
            self.connection.execute("PRAGMA journal_mode = WAL")
            self.connection.execute("PRAGMA synchronous = NORMAL")
            apply_migrations(self.connection)
        except sqlite3.DatabaseError as exc:
            self.connection.close()
            raise CorruptIndexError(
                f"Whyloom index at {path} is corrupt; delete the cache and run 'whyloom index'"
            ) from exc

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

    def all_source_hashes(self) -> dict[str, str]:
        """Indexed hash for every tracked source path, for staleness detection."""
        return {row["path"]: row["hash"] for row in self.connection.execute("SELECT path, hash FROM sources")}

    def integrity_ok(self) -> bool:
        """Run SQLite's integrity check so a corrupt cache is detected, not trusted."""
        try:
            row = self.connection.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError:
            return False
        return bool(row) and row[0] == "ok"

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
                "INSERT OR REPLACE INTO edges(source,target,type,origin,evidence,provenance,confidence,source_path,source_hash) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    edge.source,
                    edge.target,
                    edge.type,
                    edge.origin,
                    edge.evidence,
                    edge.provenance,
                    edge.confidence,
                    edge.source_path,
                    edge.source_hash,
                ),
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
        terms = _query_terms(query)
        if not terms:
            return []
        fts_query = " OR ".join(f'"{term}"' for term in terms)
        try:
            # Weight name/path matches far above body matches: a file whose path or
            # symbol whose name contains the query terms is a better hit than a file
            # that merely repeats one term in its text. bm25 column order is
            # (node_id, label, body, path); a smaller weight means a stronger signal
            # (bm25 returns more-negative = better), so label/path get low weights
            # and body a high one. Over-fetch, then re-rank by term coverage.
            rows = self.connection.execute(
                "SELECT n.*, bm25(documents, 0.0, 0.4, 5.0, 0.3) AS lexical_rank "
                "FROM documents JOIN nodes n ON n.id = documents.node_id "
                "WHERE documents MATCH ? ORDER BY lexical_rank LIMIT ?",
                # Over-fetch deeply: one symbol-dense file can otherwise fill the
                # whole pool, keeping a sparse-but-relevant file (fewer symbols)
                # out entirely so diversification has nothing to surface. FTS is
                # cheap, so a large pool is affordable.
                (fts_query, max(limit * 20, 200)),
            ).fetchall()
        except sqlite3.OperationalError:
            pattern = f"%{query}%"
            rows = self.connection.execute(
                "SELECT *, 0.0 AS lexical_rank FROM nodes WHERE label LIKE ? OR data LIKE ? LIMIT ?",
                (pattern, pattern, limit),
            ).fetchall()
        results = [self._node_dict(row) | {"lexical_rank": row["lexical_rank"]} for row in rows]
        return _rerank_by_term_coverage(results, terms)[:limit]

    def neighbors(self, node_id: str) -> list[dict]:
        rows = self.connection.execute(
            "SELECT e.*, n.id AS n_id, n.type AS n_type, n.label AS n_label, n.path AS n_path, n.source_path AS n_source_path, n.source_hash AS n_source_hash, n.data AS n_data FROM edges e JOIN nodes n ON n.id = CASE WHEN e.source = ? THEN e.target ELSE e.source END WHERE e.source = ? OR e.target = ?",
            (node_id, node_id, node_id),
        ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "edge": {
                        key: row[key]
                        for key in ("source", "target", "type", "origin", "evidence", "provenance", "confidence")
                    },
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

    def all_nodes(self) -> list[dict]:
        rows = self.connection.execute("SELECT * FROM nodes").fetchall()
        return [self._node_dict(row) for row in rows]

    def all_edges(self) -> list[dict]:
        rows = self.connection.execute(
            "SELECT source, target, type, origin, evidence, provenance, confidence FROM edges"
        ).fetchall()
        return [dict(row) for row in rows]

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
