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
4. Read `.whyloom/cache/bootstrap/request.json`, `report.md`, and `evidence.json`.
5. Query the indexed graph with `whyloom context` and `whyloom explain` for the main subsystems.
6. Inspect the highest-signal source files, tests, configuration, documentation, and Git commits cited by the evidence manifest.
7. Compare discoveries with existing records under `.whyloom/`. Do not duplicate or overwrite established reasoning.
8. Create only the smallest useful set of canonical artifacts:
   - `.whyloom/overview.md` for a repository orientation directly supported by evidence.
   - `.whyloom/glossary.md` for stable vocabulary found across multiple sources.
   - `.whyloom/proposals/inferred-*.md` for inferred architecture, decisions, or constraints.
9. Run `whyloom validate --root <root> --json`.
10. Run `whyloom onboard --complete --summary "<concise result>" --root <root> --json` to re-index and close the pending request.
11. Report created proposals, evidence gaps, open questions, and the human decisions required next.

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
- Prefer a few defensible records over comprehensive speculative documentation.
