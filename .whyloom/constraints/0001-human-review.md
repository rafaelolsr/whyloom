---
id: CON-0001
type: constraint
title: Require human review before rationale becomes authoritative
status: stable
date: 2026-07-16
targets:
  - src/whyloom/operations.py
constraints: []
supersedes: []
verified:
  - by: human:rafael
    at: "2026-08-04T00:00:00Z"
---

## Constraint

Reflection may create proposal records but must never mark them accepted or
implemented automatically.

## Evidence

`reflect_project` always writes `status: proposed` and returns
`requires_review: true`.
