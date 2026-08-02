---
id: DEC-0003
type: decision
title: Multi-language extraction via optional tree-sitter grammars
status: accepted
date: 2026-07-31
targets:
- src/whyloom/languages.py
- pyproject.toml
constraints:
- CON-0001
supersedes: []
---

## Context

Whyloom initially extracted only Python (stdlib `ast`). To match graphify's
grep-replacement value on real polyglot repos, it needed more languages, but
whyloom's identity depends on a tiny, deterministic, offline dependency surface.

## Decision

Add a generic tree-sitter adapter driven by per-grammar tables in
`languages.py`, covering TypeScript, JavaScript, Go, Rust, Java, and C#. Ship the
grammars as optional extras (`whyloom[languages]`), not base dependencies. When a
grammar is absent, degrade to a File node plus a `LANG002` warning rather than
failing the index.

## Rationale

Optional extras keep the base install (`PyYAML`, `pydantic`, `typer`) tiny and
offline. A table-driven adapter makes each new language a configuration row plus
an extra, not new code. Tree-sitter is a C parser, so extraction stays
deterministic with no LLM in the pipeline — preserving the trust model.

## Alternatives

- Bundle all grammars as hard dependencies (rejected: bloats the base install).
- Hand-write an extractor per language (rejected: unmaintainable, slow to add
  languages).
- Chase graphify's 36 languages (rejected: dilutes the deterministic identity for
  marginal reach).

## Consequences

Cross-language edges remain out of scope. Non-Python languages initially used
name-based cross-file resolution; see DEC-0005 for the alias-tracking upgrade.
