---
id: DEC-0006
type: decision
title: Cache-trust guarantees — staleness, locking, corruption detection
status: stable
date: 2026-07-31
targets:
- src/whyloom/store.py
- src/whyloom/locking.py
- src/whyloom/operations.py
constraints:
- CON-0001
supersedes: []
verified:
  - by: human:rafael
    at: "2026-08-04T00:00:00Z"
---

## Context

Agents build decisions on whyloom's index. A cache that can silently serve stale
structure, corrupt under concurrent writes, or crash on a malformed file is not
safe to rely on in a real project.

## Decision

Add three guarantees: (1) read commands warn when an indexed source no longer
matches the working tree (staleness); (2) an advisory file lock serializes index
writes so a manual index and a commit hook cannot race into corruption, with a
stale-lock self-heal; (3) a corrupt index raises a clean CorruptIndexError
(IDX003) and a failed doctor integrity check instead of an uncaught exception.

## Rationale

These convert the index from "usually right" to "trustworthy": the tool never
lets an agent act on outdated or broken data without knowing. This is the
property that distinguishes a pilot-ready cache from a demo.

## Alternatives

- Rely on SQLite WAL alone (rejected: guards statements, not a full multi-write
  index operation).
- Auto-rebuild on any corruption (deferred: explicit error plus reindex is
  simpler and lets the user decide).

## Consequences

Indexing acquires a lock; doctor gains integrity and freshness checks; retrieval
payloads may carry a staleness warning and stale_sources list.
