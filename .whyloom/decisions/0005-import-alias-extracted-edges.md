---
id: DEC-0005
type: decision
title: Import-alias tracking promotes ES/TS cross-file edges to EXTRACTED
status: stable
date: 2026-07-31
targets:
- src/whyloom/languages.py
constraints: []
supersedes: []
verified:
  - by: human:rafael
    at: "2026-08-04T00:00:00Z"
---

## Context

Name-based cross-file resolution mislinks when two files export the same name
(e.g. two `login()` functions). These edges were INFERRED with lowered
confidence, capping precision on polyglot repos.

## Decision

Parse ES/TypeScript imports into (local_name, module) pairs, resolve relative
specifiers to files, and when a call name was imported from a specific file,
resolve to that file's symbol as EXTRACTED (confidence 1.0). Keep name-based
INFERRED resolution as the fallback for unaliased calls and for languages whose
package imports do not map to files (Go/Rust/Java/C#).

## Rationale

Import statements are ground truth about which file a name comes from, so an
aliased match is unambiguous and deserves EXTRACTED provenance. Provenance stays
honest per language rather than overclaiming certainty where imports are not
file-resolvable.

## Alternatives

- Full package-path resolution for all languages (rejected: requires per-language
  project-layout knowledge; large effort, deferred).
- Leave everything INFERRED (rejected: forfeits an achievable precision win).

## Consequences

JS/TS edges from explicit imports are now trustworthy. Other languages remain
INFERRED, documented as an explicit limit.
