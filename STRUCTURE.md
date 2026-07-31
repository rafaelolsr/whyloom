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
│   ├── bootstrap.py
│   ├── installer.py
│   ├── path_policy.py
│   ├── config.py
│   ├── models.py
│   ├── records.py
│   ├── codegraph.py
│   ├── store.py
│   ├── migrations.py
│   ├── indexer.py
│   ├── retrieval.py
│   └── operations.py
├── skills/
│   ├── whyloom/SKILL.md
│   └── whyloom-bootstrap/SKILL.md
├── tests/
│   ├── fixtures/
│   └── test_*.py
└── evals/
    ├── cases/
    ├── runner.py
    └── rubric.md
```

The wheel installs the skill sources under `share/whyloom/skills/` inside the
isolated tool environment. `whyloom install` copies from that immutable bundle
into assistant-specific personal or project locations and adds an ownership
marker used for safe updates and removal.

`path_policy.py` defines generated and dependency directories that neither code
indexing nor onboarding evidence may traverse, including suffixed virtual
environments and nested `site-packages` trees.

## Structure added to an adopted codebase

```text
target-project/
├── .whyloom/
│   ├── overview.md
│   ├── architecture/
│   ├── decisions/
│   ├── constraints/
│   ├── incidents/
│   ├── glossary.md
│   ├── templates/
│   └── cache/
│       ├── graph.sqlite
│       └── bootstrap/
│           ├── evidence.json
│           ├── report.md
│           └── request.json
```

The `.whyloom/` directory is the project-memory home. Records and templates are canonical and versioned; only `.whyloom/cache/` is generated locally and ignored by Git.

Bootstrap output under `.whyloom/cache/` is disposable discovery evidence. The skill
writes inferred knowledge only to `.whyloom/proposals/`, with explicit confidence,
evidence references, open questions, and `status: proposed`.

`whyloom onboard` creates the pending request. Installed skills consume it,
validate the resulting project memory, and close it with `whyloom onboard
--complete`; `whyloom index` always reports the current lifecycle status.

## Initial graph model

### Node types

- `File`
- `Symbol`
- `ConfigKey`
- `Community`
- `Decision`
- `Constraint`
- `Rationale` — a tagged in-code comment (`WHY`, `HACK`, `NOTE`, `TODO`, `FIXME`, ...). Advisory evidence, never authoritative; ranked below governed records.

Architecture and incident records can initially be represented as typed records, then promoted to first-class nodes after the core retrieval loop is validated.

### Edge types

- `CONTAINS`: a file contains a symbol.
- `IMPORTS`: a file or symbol imports another unit.
- `CALLS`: a symbol invokes another resolved symbol.
- `INHERITS`: a class extends another resolved class.
- `REFERENCES`: code refers to another symbol or configuration key.
- `CONFIGURES`: a structured configuration file declares a key path.
- `MEMBER_OF`: an implementation file belongs to a structural community.
- `APPLIES_TO`: a decision or constraint names implementation targets.
- `IMPLEMENTS`: code implements an accepted decision.
- `CONSTRAINED_BY`: a decision, file, or symbol is governed by a constraint.
- `SUPERSEDES`: a record replaces an earlier record.
- `ANNOTATES`: a rationale comment annotates its enclosing symbol or file.

Every edge stores origin, evidence, `EXTRACTED`, `INFERRED`, or `AMBIGUOUS`
provenance, confidence, and last-indexed hash. Explicit record links outrank inferred code relationships.

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

Extracts files, symbols, imports, definitions, calls, inheritance, references,
and structured configuration keys through language adapters. A project-wide
resolution pass connects relationships that cross source files, then stable
structural communities expose coverage and cross-subsystem workflows.
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

Builds or incrementally updates the local graph. Reports changed inputs, created relationships, warnings, elapsed time, and onboarding status.

### `whyloom onboard`

Initializes an existing repository, collects bounded bootstrap evidence, and
creates an idempotent pending request for installed Whyloom skills. Status and
completion modes expose and safely close the lifecycle without accepting
agent-authored proposals automatically.

### `whyloom bootstrap`

Indexes the configured source graph and emits a bounded, deterministic evidence
manifest plus a review report. It never creates or updates canonical records.

### `whyloom explain <target>`

Returns the target's role, governing records, related code, historical supersession, evidence paths, and knowledge gaps.

### `whyloom context <task>`

Returns a compact, ranked task packet: relevant files and symbols, governing decisions, active constraints, warnings, and unresolved questions.

### `whyloom impact <target>`

Traverses outward from a file, symbol, decision, or constraint and groups likely affected artifacts by relationship and confidence.

### `whyloom path <source> <target>`

Runs a breadth-first shortest-path search between two resolved entities and returns the minimal hop sequence. Each hop names the edge type and its provenance and confidence, and the path may route through governing decisions and constraints, so the connection is auditable rather than opaque.

### `whyloom map`

Renders the indexed graph as a single self-contained HTML file with an inline, dependency-free force layout. The map is a view over the cache, never a source of truth: governed records carry a gold ring, inferred edges are dashed, and truncation is reported when the graph exceeds the drawing limit.

### `whyloom hook install` / `uninstall` / `azure`

Installs or removes client-side Git hooks (`post-commit`, `post-merge`, `post-checkout`) that run `whyloom index` so the graph tracks the working tree. Hooks are local and host-agnostic, so they work against any remote including Azure DevOps; a pre-existing non-Whyloom hook is never overwritten, and uninstall removes only Whyloom-owned hooks. `hook azure` prints an Azure Pipelines step for server-side refresh on push.

### `whyloom reflect`

Uses an explicit task summary and Git diff to create proposal files. It never changes a record to accepted automatically.

### `whyloom learnings`

Reports the state of the retro-feed loop: pending proposals awaiting human review and uncovered source files (language-source files with no `APPLIES_TO`, `IMPLEMENTS`, or `CONSTRAINED_BY` edge). `--changed` limits gaps to files changed since the last index, which is what an agent should reflect on after completing work.

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
