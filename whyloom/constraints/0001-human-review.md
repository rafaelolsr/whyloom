---
id: CON-0001
type: constraint
title: Require human review before rationale becomes authoritative
status: accepted
date: 2026-07-16
targets:
  - src/whyloom/operations.py
constraints: []
supersedes: []
---

## Constraint

Reflection may create proposal records but must never mark them accepted or
implemented automatically.

## Evidence

`reflect_project` always writes `status: proposed` and returns
`requires_review: true`.
