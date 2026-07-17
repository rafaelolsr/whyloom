# Project structure

## Source layout

```text
whyloom/
├── README.md
├── RATIONALE.md
├── DESCRIPTION.md
├── STRUCTURE.md
├── pyproject.toml
├── src/whyloom/
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── records.py
│   ├── codegraph.py
│   ├── store.py
│   ├── migrations.py
│   ├── indexer.py
│   ├── retrieval.py
│   └── operations.py
├── skills/whyloom/SKILL.md
├── tests/
│   ├── fixtures/
│   └── test_*.py
└── evals/
    ├── cases/
    ├── runner.py
    └── rubric.md
```

## Structure added to an adopted codebase

```text
target-project/
├── whyloom/
│   ├── overview.md
│   ├── architecture/
│   ├── decisions/
│   ├── constraints/
│   ├── incidents/
│   └── glossary.md
└── .whyloom/
    ├── graph.sqlite
    └── cache/
```

The `whyloom/` directory is canonical and versioned. `.whyloom/` is generated locally and ignored by Git.

## Initial graph model

### Node types

- `File`
- `Symbol`
- `Decision`
- `Constraint`

Architecture and incident records can initially be represented as typed records, then promoted to first-class nodes after the core retrieval loop is validated.

### Edge types

- `CONTAINS`: a file contains a symbol.
- `IMPORTS`: a file or symbol imports another unit.
- `APPLIES_TO`: a decision or constraint names implementation targets.
- `IMPLEMENTS`: code implements an accepted decision.
- `CONSTRAINED_BY`: a decision, file, or symbol is governed by a constraint.
- `SUPERSEDES`: a record replaces an earlier record.

Every edge stores origin, evidence, confidence, and last-indexed hash. Explicit record links outrank inferred code relationships.

## Record contract

Example decision:

```markdown
---
id: DEC-0007
type: decision
title: Keep access tokens out of browser storage
status: accepted
date: 2026-07-16
targets:
  - src/auth/token_service.py
constraints:
  - CON-0002
supersedes: []
---

## Context

What forced the decision.

## Decision

The selected approach.

## Rationale

Concise, reviewable reasoning.

## Alternatives

Options considered and why they were not selected.

## Consequences

Expected benefits, costs, and follow-up work.
```

IDs are stable. Paths may change. The index resolves current paths and preserves historical provenance.

## Component boundaries

### Record layer

Owns schemas, Markdown parsing, templates, lifecycle rules, and validation. It does not inspect programming-language syntax.

### Code graph layer

Extracts files, symbols, imports, and definitions through language adapters.
The first adapter uses Python's standard AST for a deterministic zero-compile
MVP; tree-sitter remains the planned path for widening language coverage.

### Store layer

Persists nodes, edges, source hashes, provenance, FTS documents, and schema versions in SQLite.

### Indexing layer

Coordinates record parsing and code extraction. It calculates hashes, removes obsolete generated relationships, and updates only changed sources.

### Retrieval layer

Runs FTS candidate search, expands candidates through allowed edge types and depth limits, ranks evidence, and compiles a token-bounded result.

### Command layer

Provides human-readable output and a stable JSON contract. Agent integrations call commands rather than importing internal modules.

## Retrieval flow

```text
Task or target
    ↓
Lexical candidate retrieval
    ↓
Typed graph expansion
    ↓
Lifecycle + provenance filtering
    ↓
Task-relative ranking
    ↓
Token-bounded evidence bundle
```

Ranking should favor direct explicit links, accepted status, active constraints, exact target matches, and short graph distance. Inferred links, stale evidence, and superseded records receive lower weight or are presented as warnings.

## CLI contracts

All commands support `--json` for agent use.

### `whyloom init`

Creates record directories, templates, configuration, and ignore rules. Safe to run repeatedly.

### `whyloom index`

Builds or incrementally updates the local graph. Reports changed inputs, created relationships, warnings, and elapsed time.

### `whyloom explain <target>`

Returns the target's role, governing records, related code, historical supersession, evidence paths, and knowledge gaps.

### `whyloom context <task>`

Returns a compact, ranked task packet: relevant files and symbols, governing decisions, active constraints, warnings, and unresolved questions.

### `whyloom impact <target>`

Traverses outward from a file, symbol, decision, or constraint and groups likely affected artifacts by relationship and confidence.

### `whyloom reflect`

Uses an explicit task summary and Git diff to create proposal files. It never changes a record to accepted automatically.

### `whyloom validate`

Returns nonzero for invalid schemas or broken required references. Staleness, low-confidence links, and uncovered code are warnings unless configured otherwise.

### `whyloom doctor`

Checks configuration, record structure, index presence and format, and validation
state. Returns nonzero when the repository is not ready for retrieval.

## Initial technology choices

- Python 3.11+ for the CLI and packaging.
- Typer for commands.
- Pydantic for record and output schemas.
- SQLite with FTS5 for storage and lexical retrieval.
- Python AST for the first language-aware extractor; tree-sitter is deferred.
- Markdown plus YAML frontmatter for canonical records.
- pytest for unit and integration tests.

These choices optimize for local installation, deterministic behavior, inspectable storage, and a small dependency surface. Embeddings are deliberately deferred until graph-plus-lexical retrieval has been measured.
