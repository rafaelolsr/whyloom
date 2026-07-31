---
id: DEC-0100
type: decision
title: Revoke sessions on password change
status: accepted
date: 2026-07-31
targets:
- src/session.ts
constraints: []
supersedes: []
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
