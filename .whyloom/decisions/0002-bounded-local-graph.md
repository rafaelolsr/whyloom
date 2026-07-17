---
id: DEC-0002
type: decision
title: Retrieve through a bounded local graph
status: accepted
date: 2026-07-16
targets:
  - src/whyloom/retrieval.py
  - src/whyloom/indexer.py
constraints: []
supersedes: []
---

## Decision

Use lexical candidate search followed by depth- and item-bounded traversal of
typed relationships.

## Rationale

The graph adds structural precision and speed without requiring embeddings or
a hosted service for the first validation.
