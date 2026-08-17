# Changelog

All notable changes to Whyloom. Versions are pre-1.0; minor bumps may include
model-level changes while the design settles.

## Unreleased

### Conflict detection

- `validate` now flags same-type records claiming substantially the same scope
  (target-set Jaccard ≥ 0.5 — merely touching one shared file stays silent, since
  complementary decisions legitimately co-govern a path): two authoritative
  records without a supersession link (`CONFLICT002`), and a draft covering the
  scope of an authoritative record — a supersession candidate for the reviewer
  (`CONFLICT003`). Advisory warnings, never blocking; supersession chains
  (including transitive ones) count as one lineage, not a conflict.
- `propose` surfaces these conflicts for the records it just drafted, so the
  reviewer sees them at proposal time, not at some later validate.
- Human output for `validate` and `propose` now prints warnings.

## 0.8.0 — 2026-08-10

A large release driven by piloting Whyloom on two real codebases (a Python
production repo and a Node/ESM repo). The headline change is a reframed trust
model; the rest is retrieval quality, a new command, and language support.

### Trust model — grounding replaces authorship

- **Evidence-grounding is the trust anchor.** A record governs only when its
  claims cite verifiable code; an authoritative record that grounds in nothing is
  invalid (`TRUST002`). Trust is consistency with the code, not a signature — so
  fabricated rationale cannot govern.
- **Structural facts govern human-less; the *why* stays gated.** An architecture/
  role record (what the code *is*) may be verified by a process and govern with no
  human step; a decision/constraint (the *why*) requires a human verifier
  (`TRUST001`). Onboarding can now make structure governing on its own, while any
  *why* it cannot ground is surfaced as an open question rather than asserted.
- Records align with the Open Knowledge Format: `status` uses `draft`/`stable`/
  `deprecated`; `generated`/`verified` record who produced and confirmed content;
  `accept` writes a human verification and clears machine confidence.

### Retrieval

- **New `flow` command** — traces the ordered execution skeleton from an entry
  point (the call sequence, descending into sibling methods), answering "how does
  this work" deterministically.
- Term-coverage + name/path ranking, deep over-fetch, and per-file diversification
  so lexical search surfaces the right file, not keyword-adjacent noise.
- Query stemming so natural-language queries match code vocabulary; agents are
  guided to query in code terms.
- `impact` tracks real reverse-dependency edges (no fuzzy keyword inflation),
  excludes same-file self-calls, and separates production from test callers.
- Directory record targets expand to their contained files; exact symbol names
  resolve before fuzzy search.

### Output

- `context`, `impact`, `explain`, `doctor`, and `learnings` render plain-language,
  answer-first output that routes the reader to a next step; uncovered files are
  framed as normal coverage, not a to-do list.

### Onboarding & languages

- `.mjs`/`.cjs` indexed as JavaScript; module-level calls no longer crash
  extraction.
- Self-healing index: a format-version bump triggers a rebuild on the next
  `index`, no manual cache wipe.
- Broad structural coverage on bootstrap; guidance routes each question type to
  its command (`impact`/`flow`/`explain`/`context`).

### Benchmark

- `benchmark/copilot_bench.py` compares a with/without-Whyloom Copilot run from
  Copilot's own local session log — real logged tokens, tool calls, and duration.

## 0.7.0

Source-first installation; multi-language tree-sitter grammars (Go, Rust, Java,
C#) as optional extras; removed "Git-native" framing.
