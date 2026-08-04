from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3
# The derived-graph format version. Bump this whenever node/edge extraction logic
# changes so existing per-source indexes are detected as stale and rebuilt on the
# next `index` — without it, a logic fix silently leaves old edges in place.
# 4: Rationale nodes and ANNOTATES edges.
# 5: directory record targets expand to APPLIES_TO edges per contained file
#    (previously a directory linked to a phantom `file:<dir>` node).
INDEX_FORMAT_VERSION = 5

MIGRATIONS = {
    1: """
    CREATE TABLE IF NOT EXISTS nodes (
      id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT NOT NULL, path TEXT,
      source_path TEXT NOT NULL, source_hash TEXT NOT NULL, data TEXT NOT NULL DEFAULT '{}'
    );
    CREATE TABLE IF NOT EXISTS edges (
      id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, target TEXT NOT NULL,
      type TEXT NOT NULL, origin TEXT NOT NULL, evidence TEXT NOT NULL,
      confidence REAL NOT NULL, source_path TEXT NOT NULL, source_hash TEXT NOT NULL,
      UNIQUE(source, target, type, evidence)
    );
    CREATE TABLE IF NOT EXISTS sources (
      path TEXT PRIMARY KEY, hash TEXT NOT NULL, kind TEXT NOT NULL,
      indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE VIRTUAL TABLE IF NOT EXISTS documents USING fts5(node_id UNINDEXED, label, body, path);
    CREATE INDEX IF NOT EXISTS edges_source_idx ON edges(source);
    CREATE INDEX IF NOT EXISTS edges_target_idx ON edges(target);
    CREATE INDEX IF NOT EXISTS nodes_path_idx ON nodes(path);
    """,
    2: """
    ALTER TABLE sources ADD COLUMN index_version INTEGER NOT NULL DEFAULT 0;
    """,
    3: "",
}


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS migration_history "
        "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    row = connection.execute("SELECT COALESCE(MAX(version), 0) FROM migration_history").fetchone()
    current = int(row[0])
    if current > SCHEMA_VERSION:
        raise RuntimeError(f"graph schema {current} is newer than supported version {SCHEMA_VERSION}")
    for version in range(current + 1, SCHEMA_VERSION + 1):
        if version == 3:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS edges ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, target TEXT NOT NULL, "
                "type TEXT NOT NULL, origin TEXT NOT NULL, evidence TEXT NOT NULL, "
                "confidence REAL NOT NULL, source_path TEXT NOT NULL, source_hash TEXT NOT NULL, "
                "provenance TEXT NOT NULL DEFAULT 'EXTRACTED', UNIQUE(source, target, type, evidence))"
            )
            columns = {row[1] for row in connection.execute("PRAGMA table_info(edges)")}
            if "provenance" not in columns:
                connection.execute("ALTER TABLE edges ADD COLUMN provenance TEXT NOT NULL DEFAULT 'EXTRACTED'")
            connection.execute("INSERT INTO migration_history(version) VALUES (?)", (version,))
            continue
        migration = MIGRATIONS.get(version)
        if migration is None:
            raise RuntimeError(f"missing graph migration {version}")
        connection.executescript(migration)
        connection.execute("INSERT INTO migration_history(version) VALUES (?)", (version,))
    connection.commit()
