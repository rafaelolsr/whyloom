# Agent JSON contract

All commands accept `--json` and return one JSON object on standard output.
Every object includes `schema_version`. Operational failures use
`{"ok": false, "error": {"code": "...", "message": "..."}}` and a nonzero
exit status.
Fields may be added in minor releases; existing fields keep their meaning within
the `0.x` MVP line.

## Shared evidence shape

Graph evidence contains `id`, `type`, `label`, `path`, `source_path`,
`source_hash`, `data`, `distance`, `score`, and the typed `via` edge when the
item was reached by traversal. Every relationship includes its origin,
`EXTRACTED`, `INFERRED`, or `AMBIGUOUS` provenance, confidence, and
evidence path so an agent can verify it before acting.

## Command guarantees

- `install`: operation, project scope, and one result per platform and skill with destination and action.
- `uninstall`: removes only Whyloom-owned skill directories and reports absent directories without error.
- `index`: changed, unchanged, and removed sources, structural coverage and its
  manifest path, diagnostics, and current onboarding status.
- `onboard`: initialization and bootstrap results plus a `pending`, `completed`,
  `not_started`, or `invalid` onboarding lifecycle. `--complete` requires a
  summary and valid project memory before closing a request.
- `bootstrap`: index result, stratified evidence coverage, structural community
  coverage, generated manifest and report paths,
  truncation state, and `canonical_records_changed: false`.
- `context`: task, governing records, files, evidence, warnings, and unresolved questions.
  With `--compact`, evidence is reduced to governing records, files, symbols,
  relationships, communities, warnings, and unresolved questions.
- `explain`: target resolution, governing records, related code, evidence, and knowledge gaps.
- `impact`: affected code and records plus traversal evidence.
- `validate`: validity, record count, errors, and warnings; exits nonzero when
  invalid. Warnings include scope conflicts: `CONFLICT002` (two authoritative
  same-type records claim substantially the same targets without a supersession
  link) and `CONFLICT003` (a draft covers the scope of an authoritative record —
  a supersession candidate). Conflicts are advisory and never fail validation.
- `propose`: created proposals, skip count, and `conflicts` — the target-conflict
  warnings that involve the records just drafted.
- `reflect`: proposal path, changed paths, and `requires_review: true`.
- `doctor`: readiness checks for repository, configuration, records, index, and validation.

Generated graph data is evidence, not authority. Cite the canonical record or
source path when using a result to justify a change.

Bootstrap evidence uses `id`, `kind`, `source`, `locator`, and `summary`. The
manifest always declares `authoritative: false`. Inferred canonical records may
add `confidence`, structured `evidence`, and `open_questions`, but remain
non-governing while their status is `proposed`.
