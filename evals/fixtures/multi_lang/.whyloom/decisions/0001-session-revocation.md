---
id: DEC-0100
type: decision
title: Revoke sessions on password change
status: stable
date: 2026-07-31
targets:
- src/session.ts
constraints: []
supersedes: []
verified:
  - by: human:maintainer
    at: "2026-07-31T00:00:00Z"
---

## Context
Stolen tokens stay valid after a password change unless sessions are revoked.

## Decision
On password change, revoke all sessions for the user.

## Rationale
Closes the stolen-token replay window.

## Alternatives
Short TTL only (rejected: shrinks but does not close the window).

## Consequences
Requires a server-side session store.
