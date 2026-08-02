---
id: DEC-0004
type: decision
title: Extracted rationale is advisory, ranked below governed records
status: accepted
date: 2026-07-31
targets:
- src/whyloom/languages.py
- src/whyloom/retrieval.py
constraints:
- CON-0001
supersedes: []
---

## Context

Tagged in-code comments (WHY/HACK/TODO/FIXME) carry real intent and should be
queryable. But a comment is not a reviewed decision; treating it as authoritative
would let unreviewed text govern the project, breaking the trust model.

## Decision

Extract tagged comments as first-class `Rationale` nodes linked to their
enclosing symbol via `ANNOTATES`. Make them reachable by explain/context/path but
weight them below code and governed records, so an accepted Decision or
Constraint always outranks a rationale comment.

## Rationale

This captures the signal (the comment exists, EXTRACTED) without granting it
authority. It mirrors the core separation: code is implementation truth, accepted
records are intent truth, and everything inferred is advisory until a human
accepts it.

## Alternatives

- Promote comments straight to decisions (rejected: unreviewed intent becomes
  authoritative).
- Ignore comments entirely (rejected: loses real rationale the author wrote).

## Consequences

A string-context guard rejects comment markers inside string literals to avoid
false positives. Retrieval ranking gives ANNOTATES a low edge weight.
