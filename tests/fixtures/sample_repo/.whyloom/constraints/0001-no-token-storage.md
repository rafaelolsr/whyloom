---
id: CON-0001
type: constraint
title: Never persist raw credentials
status: stable
date: 2026-07-16
targets:
  - src/sample/auth.py
constraints: []
supersedes: []
verified:
  - by: human:maintainer
    at: "2026-07-31T00:00:00Z"
---

## Constraint

Raw credentials must never be persisted or returned to a browser.

