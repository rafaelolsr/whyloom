---
id: DEC-0008
type: decision
title: Anchor record trust on evidence-grounding, not human authorship
status: stable
date: 2026-08-05
targets:
  - src/whyloom/operations.py
  - src/whyloom/models.py
  - skills/whyloom/SKILL.md
constraints:
  - CON-0001
supersedes:
  - DEC-0004
verified:
  - by: human:rafael
    at: "2026-08-05T00:00:00Z"
---

## Context

Whyloom's founding thesis was: *nothing an agent inferred becomes authoritative
until a human accepts it.* The load-bearing assumption was that human acceptance
equals review — a person exercising judgment before a record governs.

In practice, when a user vibe-codes, the agent writes the code, the agent writes
the rationale, the user supplied only an intention, and `accept` is a keystroke.
The human contributes no verification. The gate the whole product was built on is
theater: a signature on text the human did not author about code the human did
not write. That is worse than no rationale — false confidence stamped as
authoritative, trusted by the next reader.

Human authorship is the wrong trust anchor for agent-assisted work: it is
unverifiable, unenforceable, and collapses to a rubber stamp the moment vouching
is free.

## Decision

Shift the trust anchor from **who authored a record** to **whether its claims are
grounded in verifiable code**. A record earns authority when:

1. Every substantive claim cites concrete evidence — a `targets` path and/or an
   `evidence[].source` that names a real file or symbol in the graph.
2. Whyloom can verify those citations resolve (the file/symbol exists; the target
   is a real node), deterministically, at `validate` time.
3. Claims that cannot be grounded in the change are recorded as `open_questions`,
   never asserted as rationale.

The code is the referee. The agent may author; the human owns the *intention*
(the `reflect` summary) and confirms it; but a record does not govern on a
signature alone — it governs because its evidence checks out.

## Rationale

The one property that is checkable, deterministic, and un-fakeable is consistency
with the code. Anchoring on evidence catches the common, dangerous failure —
hallucinated rationale — because a fabricated "why" cites nothing that resolves.
It keeps the agent productive (it can author) and the human honest (they own
intention, not fiction), without demanding authorship the human cannot provide.

## Alternatives

- **Keep human-authorship as the anchor** (the original thesis): rejected — it is
  a rubber stamp under vibe-coding and produces either fake reviews or no
  reflection at all.
- **Require a real human to author every rationale**: rejected — unenforceable and
  kills adoption; humans in agent workflows genuinely lack the micro-decision
  context to author it.

## Consequences

- `validate` gains an evidence-grounding check: a stable record whose claims cite
  no resolvable file/symbol is invalid, not merely unreviewed.
- `reflect` scaffolds per-claim evidence and forces ungrounded statements into
  `open_questions`.
- `accept` means "intention owned + evidence verified", not "a human read prose".
- Retrieval can rank evidence-verified records above asserted, unverified ones.
- Honest limitation: evidence-grounding catches **hallucinated** rationale, not
  **well-cited bad judgment** — an agent can cite real code for a strategically
  wrong decision. This anchor verifies consistency with code, not correctness of
  intent. That is a weaker but real and defensible claim, and far stronger than a
  rubber stamp.
- Supersedes DEC-0004 (rationale advisory vs authoritative), which framed trust
  around review status rather than evidence.
