---
id: DEC-0001
type: decision
title: Keep project intent canonical in Git
status: accepted
date: 2026-07-16
targets:
  - src/whyloom/records.py
  - src/whyloom/store.py
constraints:
  - CON-0001
supersedes: []
---

## Decision

Store reviewed decisions and constraints as Markdown in the repository. Treat
SQLite as a disposable retrieval index that can always be rebuilt.

## Rationale

Humans and agents need the same inspectable, reviewable source of project
meaning. Generated graph state must not become a second authority.
