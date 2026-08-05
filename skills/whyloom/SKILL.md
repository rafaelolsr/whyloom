---
name: whyloom
description: Retrieve and verify a codebase's recorded decisions, constraints, and implementation relationships with the Whyloom CLI. Use before changing unfamiliar or rationale-sensitive code, when a task refers to prior project decisions, when explaining why code exists, when checking change impact, after work that may have produced a durable project learning, or when a repository has a pending Whyloom onboarding request.
---

# Whyloom

Use Whyloom as a pre-flight check for project meaning. Prefer cited canonical
records over guesses from code shape or chat history.

## Resolve onboarding first

1. Run `whyloom onboard --status --json`.
2. If status is `pending`, invoke `$whyloom-bootstrap` immediately for **broad
   coverage** — an architecture-role record for every significant subsystem, not a
   token few. Do not wait for the user to know or repeat a bootstrap prompt.
3. If status is `not_started` and the repository has no reliable Whyloom
   records, run `whyloom onboard --json`, then invoke `$whyloom-bootstrap`.
4. Return to the current task only after onboarding is completed or after
   reporting evidence too weak to support project-memory changes.

Do not use the ongoing reflection loop to fabricate an initial project history.

## Gather context before changing code

1. Find the repository root containing `whyloom.yaml`.
2. Resolve the onboarding lifecycle above.
3. Run `whyloom doctor --json` to identify missing configuration, index, or invalid records.
4. Run `whyloom index --json` when the index may be absent or stale.
5. Run `whyloom context "<current task>" --compact --json`.
6. Read the returned governing records, symbols, relationships, communities, and source paths.
7. Also read `proposed_records`: on a freshly onboarded codebase most rationale is
   still `proposed` (unreviewed). Use it as day-one evidence — it is a real, cited
   starting point — but treat it as unverified: confirm it against the cited files
   before relying on it, and never present it as accepted project intent.
8. Treat `EXTRACTED` relationships as structural evidence and `INFERRED` or
   `AMBIGUOUS` relationships as prompts for source verification.
9. Verify high-impact claims in the cited files before editing.
10. Surface warnings and unresolved questions instead of manufacturing intent.

If neither a governing record nor a proposed record is returned, say that rationale
is unrecorded. Do not treat missing knowledge as permission to invent a project
decision. A proposed record is evidence to verify, not authority to cite.

## Explain or assess impact

- Run `whyloom explain <path-or-node-id> --json` to explain what a target does,
  why it exists, and where rationale is missing.
- Run `whyloom impact <path-or-record-id> --json` before changing a governing
  record or implementation with linked dependents.
- Run `whyloom validate --json` when records or linked paths changed. Stop on
  validation errors.

## Capture learning after work

First check whether the work left uncovered rationale:

```bash
whyloom learnings --changed --json
```

If it reports uncovered source files that you changed, those are rationale gaps
you should close before finishing. Then run:

```bash
whyloom reflect "<what changed and why>" --json
```

The command returns an `agent_brief` (the task summary, changed paths, and the
symbols in each changed file) and writes a proposal skeleton with `<!-- agent: -->`
prompts. Complete it yourself: open the generated proposal and fill the
`Decision`, `Rationale`, `Alternatives`, `Consequences`, and `Open questions`
sections from the brief and the diff. Ground every claim in the listed evidence
paths and symbols, state confidence, and record anything uncertain as an open
question instead of inventing rationale. Leave the record `proposed` for normal
human review. Never accept a record on the agent's own authority.

Reflect works without Git: when no repository or diff is available it detects
changed files from the index (`baseline: filesystem`), so it can capture learning
in any folder.

## Evidence rules

- Prefer accepted or implemented records for governing intent.
- Preserve record IDs and source paths in the response.
- Distinguish explicit record links from inferred code relationships.
- Cite relationship evidence and provenance when explaining an implementation path.
- Treat `.whyloom/cache/graph.sqlite` as a cache, never as canonical truth.
- Do not request or store private chain-of-thought; capture concise rationale,
  evidence, alternatives, and consequences.
