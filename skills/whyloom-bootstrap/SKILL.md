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
     onboarding with usable orientation across its subsystems, not a token few
     records. Most subsystems will not have a documented *decision*; propose an
     **architecture-role record** for them instead (see "Two kinds of record").
     Each proposal still lands as `status: proposed` for human review; breadth is
     safe precisely because nothing is authoritative until accepted.
10. Run `whyloom validate --root <root> --json`.
11. Run `whyloom onboard --complete --summary "<concise result>" --root <root> --json` to re-index and close the pending request.
12. Report created proposals, uncovered communities, evidence gaps, open questions, and the human decisions required next.

## Two kinds of record

Onboarding an existing codebase produces two distinct, equally valid proposal
kinds. Do not withhold a record just because the subsystem has no documented
*decision* — most won't, and role coverage is the point of onboarding.

**Decision / constraint record** — claims *why a choice was made* ("tokens are
kept out of browser storage because ..."). Requires decision-grade evidence: a
plan, an ADR, a commit rationale, or a comment stating intent. Without that
evidence, do not invent one — record an open question.

**Architecture-role record** — claims *what a subsystem is and what it owns*
("`src/state/` is the conversation-persistence boundary: it owns session storage,
checkpointing, and episodic/semantic stores; callers reach it only through
`ConversationStore`"). This is grounded in **structural evidence you can cite** —
imports, containment, what calls it, what it calls — not speculation. A role
record is well-evidenced by structure even when no decision is documented. Give
every significant community one, with `type: architecture` and a
`## Role` / `## Responsibilities` / `## Boundaries` body. State it as an observed
role, and put any *why* you cannot support in `open_questions`.

The evidence bar is not lower for role records — it is *different*: structure
must demonstrably support the role claim. What stays forbidden is inventing a
*rationale* (a why) that no evidence supports.

## Record contract — grounding decides trust, not authorship (DEC-0008)

The two record kinds are trusted differently, because one is provable from code
and the other is not.

**Architecture / structural-role records — may govern without a human.** These
state what the code *is* (boundaries, ownership, what calls what) and are provable
from evidence. When every claim cites resolvable code, emit them ready to govern:

- `type: architecture`
- `status: stable`
- `verified:` a single `- by: process:bootstrap` entry with an ISO `at:` timestamp
- `generated:` `{ by: "<your agent id>", at: <timestamp> }`
- repository-relative `targets` that resolve, and `evidence` entries naming real files
- body: `## Role` / `## Responsibilities` / `## Boundaries`, each claim traceable to
  the cited code

A grounded structural record passes `TRUST001` (process-verified) and `TRUST002`
(grounded), so it governs immediately — no human step. An ungrounded one is
rejected, so never emit a structural claim you cannot cite.

**Decision / constraint records — the WHY — never assert it; ask it.** Why a
choice was made is *not* in the code; inferring it is fabricating history, which
`TRUST002`/`TRUST001` reject. Do **not** emit `type: decision` rationale from
onboarding. Instead, when the code shows a shape whose reason is unrecorded,
capture it as an **open question on the structural record**:

> `## Open questions`
> `- The code shows tokens are stored httpOnly (src/auth.py:rotate). The *reason*
>   is unrecorded — likely XSS mitigation, framework default, or convention.
>   Human: which was it?`

This surfaces the decision for a human to confirm cheaply, without asserting a
guess. A real decision record is created later, by a human or via `reflect` on an
actual change — always with a human verifier.

Use a stable ID such as `ARC-INFERRED-001` for structural records.

Separate observation from inference in the body. State what the evidence
demonstrates and what a reader must still confirm.

## Guardrails

- A structural (architecture) record may be `stable` + `process:bootstrap`
  verified ONLY when every claim cites resolvable code. Never mark a
  decision/constraint (a why) stable — those require a human verifier.
- Never manufacture a *rationale* (a claimed why) from code shape, dependency
  choice, or naming alone. Describing a subsystem's structural *role* from cited
  imports/containment/callers is not manufacturing rationale — it is the intended
  content of an architecture-role record. An unrecorded *why* is an open question,
  never an asserted decision record.
- Never treat Git commit subjects or comments as unquestionable truth.
- Never copy secrets, credentials, large source excerpts, or private data into records.
- Never emit a record — even structural — whose claims you cannot cite in code;
  it fails validation (TRUST002). Record an open question instead.
- Never treat Git commit subjects or comments as unquestionable truth.
- Never copy secrets, credentials, large source excerpts, or private data into records.
- Never create a proposal when even the structural evidence is too weak to support
  the claim; record an open question instead.
- Favor broad coverage: every significant community deserves at least a role
  record. Do not pad — a claim structure cannot support is worse than a gap — but
  do not withhold a well-evidenced role record merely because no decision is
  documented. Breadth comes from covering more *real* boundaries by role, while the
  evidence bar for each claim stays intact.
