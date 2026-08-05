---
id: DEC-0007
type: decision
title: Align record frontmatter with the Open Knowledge Format
status: stable
date: 2026-08-04
targets:
  - src/whyloom/models.py
  - src/whyloom/operations.py
  - src/whyloom/records.py
constraints:
  - CON-0001
supersedes: []
verified:
  - by: human:rafael
    at: "2026-08-04T00:00:00Z"
---

## Context

Whyloom records are Markdown files with YAML frontmatter carrying provenance, a
trust lifecycle, and typed links — a format arrived at independently. Google's
Open Knowledge Format (OKF, `GoogleCloudPlatform/knowledge-catalog`) standardizes
the same idea for agent-generated knowledge: Markdown + YAML, first-class
provenance (`sources`), trust (`generated`, `verified`), and lifecycle (`status`,
`stale_after`). OKF is permissive — consumers must preserve unknown keys and must
not reject unrecognized fields — so alignment can be additive.

## Decision

Adopt the OKF trust model as whyloom's native record shape:

- `status` uses OKF values: `draft` | `stable` | `deprecated` (legacy `proposed`
  maps to `draft`, `accepted`/`implemented` to `stable`, `superseded` to
  `deprecated`; legacy values still parse).
- `generated: {by, at}` records who produced the current content, using the OKF
  actor convention (`<producer>/<version>` for agents, `human:<id>` for people).
  This replaces the heuristic that inferred agent-authorship from an `INFERRED`
  id or a `confidence` score.
- `verified: [{by, at}]` records each human/process confirmation. **A human
  `verified[]` entry is the review gate**: a record is authoritative only when a
  human has verified it. `accept` appends this entry and flips `draft → stable`.
- `sources: [{resource, ...}]` is accepted as an alias for whyloom `evidence`.

`TRUST001` becomes exact rather than heuristic: it fires when a record is
`stable` (or otherwise governing) but carries no human `verified[]` entry — the
authoritative-without-review case whyloom exists to prevent.

## Rationale

OKF's trust model is a superset of whyloom's and is better in two places: it
records *who* verified and *when* (an audit trail whyloom lacked), and it states
generation explicitly instead of inferring it. Aligning sharpens the trust gate,
makes records portable to any OKF consumer, and costs little because OKF is
additive — whyloom keeps its own fields (`type` enum, `targets`, `constraints`,
`supersedes`) alongside the OKF ones.

## Alternatives

- Keep whyloom's `proposed/accepted` vocabulary and map only at export: rejected
  — it leaves two vocabularies to maintain and keeps the gate as a status flip
  rather than an auditable verification event.
- Ignore OKF, stay independent: rejected — forgoes portability and a strictly
  better provenance model for no benefit, given the additive migration path.

## Consequences

- Existing records migrate: `status` values map forward; a `verified[]` entry is
  synthesized for already-accepted records so they stay authoritative.
- The `_looks_inferred` heuristic is retired in favor of reading `generated.by`.
- A future `whyloom export okf` can emit fully-conformant bundles.
- Open question: whether to also adopt `stale_after` (absolute date) in addition
  to whyloom's content-hash staleness — deferred; the two are complementary.
