---
name: whyloom
description: Retrieve and verify a codebase's recorded decisions, constraints, and implementation relationships with the Whyloom CLI. Use before changing unfamiliar or rationale-sensitive code, when a task refers to prior project decisions, when explaining why code exists, when checking change impact, after work that may have produced a durable project learning, or when a repository has a pending Whyloom onboarding request.
---

# Whyloom

Use Whyloom as a pre-flight check for project meaning. Prefer cited canonical
records over guesses from code shape or chat history.

## Resolve onboarding first

1. Run `whyloom onboard --status --json`.
2. If status is `pending`, invoke `$whyloom-bootstrap` immediately. Do not wait
   for the user to know or repeat a bootstrap prompt.
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
6. Read the returned governing records and relevant source paths.
7. Verify high-impact claims in those files before editing.
8. Surface warnings and unresolved questions instead of manufacturing intent.

If no governing record is returned, say that rationale is unrecorded. Do not
treat missing knowledge as permission to invent a project decision.

## Explain or assess impact

- Run `whyloom explain <path-or-node-id> --json` to explain what a target does,
  why it exists, and where rationale is missing.
- Run `whyloom impact <path-or-record-id> --json` before changing a governing
  record or implementation with linked dependents.
- Run `whyloom validate --json` when records or linked paths changed. Stop on
  validation errors.

## Capture learning after work

Run:

```bash
whyloom reflect --task-summary "<what changed and why>" --json
```

Open the generated proposal, replace placeholder language with concise evidence,
and leave it `proposed` for normal human review. Never accept a record on the
agent's own authority.

## Evidence rules

- Prefer accepted or implemented records for governing intent.
- Preserve record IDs and source paths in the response.
- Distinguish explicit record links from inferred code relationships.
- Treat `.whyloom/cache/graph.sqlite` as a cache, never as canonical truth.
- Do not request or store private chain-of-thought; capture concise rationale,
  evidence, alternatives, and consequences.
