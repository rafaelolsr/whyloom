---
name: whyloom-bootstrap
description: Complete evidence-backed Whyloom onboarding for an existing codebase. Use when `.whyloom/cache/bootstrap/request.json` is pending, when `whyloom onboard` prepared repository evidence, when a repository lacks reliable architecture, decision, constraint, or glossary records, or when reconstructing project intent without presenting inference as established truth.
---

# Bootstrap Whyloom

Recover project reasoning as reviewable proposals. Treat code as evidence of what exists, not proof of why it exists.

## Workflow

1. Locate the repository root and read `AGENTS.md`, `CLAUDE.md`, or equivalent project instructions.
2. Run `whyloom onboard --status --root <root> --json`.
3. If status is `not_started`, run `whyloom onboard --root <root> --json`. If status is `completed`, stop unless the user explicitly requests a fresh onboarding run.
4. Read `.whyloom/cache/bootstrap/request.json`, `report.md`, `evidence.json`,
   and `.whyloom/cache/coverage.json`.
5. Account for every significant structural community as analyzed, deliberately
   skipped, or unresolved. Do not let one evidence category consume the review.
6. Trace the highest-signal cross-community relationships with `whyloom context`
   and `whyloom explain`, prioritizing authentication, external APIs,
   persistence, deployment, and other runtime boundaries.
7. Inspect the cited source files, tests, configuration, documentation, and Git commits.
8. Compare discoveries with existing records under `.whyloom/`. Do not duplicate or overwrite established reasoning.
9. Create canonical artifacts with broad, evidence-backed coverage:
   - `.whyloom/overview.md` for a repository orientation directly supported by evidence.
   - `.whyloom/glossary.md` for stable vocabulary found across multiple sources.
   - `.whyloom/proposals/inferred-*.md` for inferred architecture, decisions, or
     constraints. Aim to cover **every significant structural community and runtime
     boundary** with at least one proposal — an existing codebase should come out of
     onboarding with usable rationale across its subsystems, not a token few records.
     Each proposal still lands as `status: proposed` for human review; breadth is
     safe precisely because nothing is authoritative until accepted.
10. Run `whyloom validate --root <root> --json`.
11. Run `whyloom onboard --complete --summary "<concise result>" --root <root> --json` to re-index and close the pending request.
12. Report created proposals, uncovered communities, evidence gaps, open questions, and the human decisions required next.

## Proposal contract

Give every inferred record:

- `status: proposed`
- `confidence: low|medium|high`
- `evidence` entries with `kind`, `source`, and a factual `summary`
- `open_questions` for uncertainty that evidence cannot resolve
- repository-relative `targets` when the claim applies to concrete files

Use a stable ID such as `DEC-INFERRED-001`, `CON-INFERRED-001`, or `ARC-INFERRED-001`.

Separate observation from inference in the body. State what the evidence demonstrates, what is inferred, what alternatives remain plausible, and what a reviewer must confirm.

## Guardrails

- Never change an inferred record to `accepted` or `implemented`.
- Never manufacture rationale from code shape, dependency choice, or naming alone.
- Never treat Git commit subjects or comments as unquestionable truth.
- Never copy secrets, credentials, large source excerpts, or private data into records.
- Never create a proposal when the evidence is too weak; record an open question instead.
- Favor broad coverage of evidence-backed subsystems, but never pad: a proposal
  with weak evidence is worse than an acknowledged gap. Breadth comes from covering
  more *real* boundaries, not from lowering the evidence bar on any one of them.
