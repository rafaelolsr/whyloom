---
name: whyloom-bootstrap
description: Analyze an existing codebase and bootstrap evidence-backed Whyloom project memory. Use when onboarding a repository that lacks reliable architecture, decision, constraint, or glossary records; when reconstructing project intent from code, tests, configuration, documentation, and Git history; or when asked to initialize Whyloom without presenting inferred rationale as established truth.
---

# Bootstrap Whyloom

Recover project reasoning as reviewable proposals. Treat code as evidence of what exists, not proof of why it exists.

## Workflow

1. Locate the repository root and read `AGENTS.md`, `CLAUDE.md`, or equivalent project instructions.
2. Run `whyloom bootstrap --root <root> --json`.
3. Read `.whyloom/cache/bootstrap/report.md` and `.whyloom/cache/bootstrap/evidence.json`.
4. Query the indexed graph with `whyloom context` and `whyloom explain` for the main subsystems.
5. Inspect the highest-signal source files, tests, configuration, documentation, and Git commits cited by the evidence manifest.
6. Compare discoveries with existing records under `.whyloom/`. Do not duplicate or overwrite established reasoning.
7. Create only the smallest useful set of canonical artifacts:
   - `.whyloom/overview.md` for a repository orientation directly supported by evidence.
   - `.whyloom/glossary.md` for stable vocabulary found across multiple sources.
   - `.whyloom/proposals/inferred-*.md` for inferred architecture, decisions, or constraints.
8. Run `whyloom validate`, then `whyloom index`.
9. Report created proposals, evidence gaps, open questions, and the human decisions required next.

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
