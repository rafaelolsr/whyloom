# Whyloom

![Whyloom weaves code, decisions, constraints, and history into a living project-memory graph](docs/assets/whyloom-hero.png)

> Your codebase remembers why.

Whyloom is a Git-native, graph-backed project memory for a single codebase. It connects implementation facts to the decisions, constraints, rejected alternatives, and operational lessons that explain them, then gives humans and coding agents fast, task-specific context.

## The problem

Teams increasingly delegate both implementation and design reasoning to coding agents. The code survives, but much of the reasoning disappears into chat histories, compaction summaries, pull requests, and individual memory.

The next agent can inspect what the code does but often cannot determine:

- why the implementation took this shape;
- which constraints must remain true;
- which alternatives were rejected and why;
- which decision superseded an older one;
- what an incident taught the project;
- which context matters for the task at hand.

Long context windows and semantic search do not solve this reliably. They can return related information without reconstructing the project's meaning.

## The product

Whyloom maintains two connected forms of project knowledge:

1. **Canonical project records in Git** — concise Markdown records for decisions, constraints, architecture, incidents, and terminology.
2. **A generated local graph** — files, symbols, records, and typed relationships indexed for fast, bounded traversal.

The repository remains the source of truth. The graph is disposable and can always be rebuilt.

```text
Code + project records
        ↓
Incremental indexer
        ↓
Local rationale graph
        ↓
Task-specific context for humans and agents
```

## Core workflow

```bash
whyloom init
whyloom index
whyloom explain src/auth/token_service.py
whyloom context "change refresh-token rotation"
whyloom impact decisions/0007-token-storage.md
whyloom reflect
whyloom validate
whyloom doctor
```

- `init` adds the canonical project-memory structure.
- `index` extracts code structure and links it to project records.
- `explain` answers what a path or symbol does and why it exists.
- `context` builds a compact evidence bundle for a task.
- `impact` shows the code and records affected by a change.
- `reflect` proposes new or updated records after work is completed.
- `validate` detects broken links, stale records, and contradictory active constraints.
- `doctor` verifies that configuration, records, index, and validation are ready.

## Bootstrap an existing codebase

Use the separate bootstrap workflow when a repository has code but little reliable project reasoning:

```bash
whyloom bootstrap --root . --json
```

This indexes the repository and writes a bounded evidence manifest plus a review report under `.whyloom/cache/bootstrap/`. It does not change canonical records. Invoke the portable `whyloom-bootstrap` skill to inspect that evidence and create proposed records with explicit confidence, citations, and open questions.

Inferred rationale is never authoritative. A human must review it before changing its status to `accepted` or `implemented`.

## Trust model

Whyloom separates implementation truth from project intent:

- code is the source of truth for implementation;
- tests are the source of truth for observed behavior;
- accepted project records are the source of truth for intent and rationale;
- the generated index is a cache, never an authority;
- agent-generated knowledge enters as a proposal and requires normal Git review before becoming accepted truth.

Whyloom stores concise rationale and evidence, not private model chain-of-thought.

## MVP

The first release proves one claim:

> Linking decisions and constraints directly to code through a local graph gives agents more useful context, faster, than reading undifferentiated documentation.

The MVP includes:

- Markdown records with YAML frontmatter;
- nodes for files, symbols, decisions, and constraints;
- typed links between records and implementation;
- incremental local indexing;
- full-text retrieval plus bounded graph traversal;
- `init`, `index`, `explain`, `context`, `impact`, `reflect`, and `validate` commands;
- a portable Claude Code/Codex-style skill that invokes the CLI;
- fixtures and an A/B evaluation against plain repository documentation.

The MVP does not include a hosted service, accounts, cross-repository knowledge, a web dashboard, automatic acceptance of agent-authored records, or enterprise governance.

## Repository documents

- [RATIONALE.md](RATIONALE.md) — why this should exist and how the hypothesis will be tested.
- [DESCRIPTION.md](DESCRIPTION.md) — users, workflows, requirements, and MVP boundaries.
- [STRUCTURE.md](STRUCTURE.md) — repository layout, graph model, components, and command contracts.

## Status

Beta CLI ready for real codebase pilots. The CLI initializes a repository, parses canonical records,
incrementally indexes Python files into SQLite, retrieves bounded task context,
explains and traces impact, validates record drift, and creates human-governed
reflection proposals. The included skill and evaluation fixture exercise the
same public command contract.

## Development

```bash
uv sync --extra dev
uv run pytest -q
uv run whyloom index --json
uv run whyloom context "change graph storage safely" --json
uv run whyloom doctor --json
uv run python evals/runner.py
```

For agent calls, add `--compact` to `context` to return only governing record
references, relevant files, warnings, and unresolved questions.

See [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) for guarantees,
release gates, and explicit beta limits.
