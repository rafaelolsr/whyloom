---
id: DEC-0001
type: decision
title: Keep tokens out of browser storage
status: accepted
date: 2026-07-16
targets:
  - src/sample/auth.py
constraints:
  - CON-0001
supersedes: []
---

## Decision

Token material remains server-side. Only fingerprints may be persisted.

## Rationale

Browser storage would expand the credential exposure surface.

