<div align="center">

<img src="docs/assets/whyloom-banner.svg" alt="Whyloom — weave code and its reasoning into one graph" width="100%">

# Whyloom

**Your codebase remembers why.** *A Git-native, graph-backed project memory that links code to the decisions, constraints, and rejected alternatives that explain it — then hands agents fast, task-specific context.*

[![CI](https://github.com/rafaelolsr/whyloom/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelolsr/whyloom/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/whyloom.svg)](https://pypi.org/project/whyloom/)
[![Python](https://img.shields.io/pypi/pyversions/whyloom.svg)](https://pypi.org/project/whyloom/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Works with **Claude Code · Codex · GitHub Copilot · Agent Skills** — one deterministic CLI, portable skills, a tiny dependency surface, and nothing that leaves your machine.

[Install](#install) · [Core workflow](#core-workflow) · [Onboard a codebase](#onboard-an-existing-codebase) · [Trust model](#trust-model) · [How it works](STRUCTURE.md) · [Docs](#repository-documents)

</div>

---

## What is Whyloom?

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
2. **A generated local graph** — files, symbols, configuration keys, structural
   communities, records, and typed relationships indexed for fast, bounded traversal.

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

## Install

Install the isolated CLI from PyPI:

```bash
uv tool install whyloom
whyloom install
```

`whyloom install` registers both the ongoing `whyloom` skill and the one-time
`whyloom-bootstrap` skill. With no platform option, it installs into every
detected supported assistant and falls back to the generic Agent Skills location.

Choose a platform or commit the skills with a project explicitly:

```bash
whyloom install --platform codex
whyloom install --platform claude
whyloom install --platform copilot
whyloom install --platform agents

whyloom install --platform copilot --project --root .
```

For an existing repository, prepare project memory with one command:

```bash
whyloom onboard --root .
```

This initializes Whyloom, indexes the codebase, collects bounded evidence, and
creates a pending onboarding request. The installed Whyloom skill detects that
request and turns defensible findings into reviewable proposals; the user does
not need to know a separate bootstrap prompt.

| Platform | Personal skills | Project skills |
|---|---|---|
| Codex | `~/.codex/skills/` | `.agents/skills/` |
| Claude | `~/.claude/skills/` | `.claude/skills/` |
| GitHub Copilot | `~/.copilot/skills/` | `.github/skills/` |
| Agent Skills | `~/.agents/skills/` | `.agents/skills/` |

Project-scoped Copilot skills work with Copilot coding agent, Copilot CLI, and
agent mode in VS Code. To remove only directories managed by Whyloom:

```bash
whyloom uninstall --platform copilot
```

To test the latest unreleased development version instead:

```bash
uv tool install git+https://github.com/rafaelolsr/whyloom.git
```

## Core workflow

```bash
whyloom onboard
whyloom index
whyloom explain src/auth/token_service.py
whyloom context "change refresh-token rotation"
whyloom impact decisions/0007-token-storage.md
whyloom reflect --task-summary "describe the durable project learning"
whyloom validate
whyloom doctor
```

- `onboard` initializes an existing repository and prepares evidence for automatic agent review.
- `init` adds only the canonical project-memory structure.
- `index` extracts code structure and links it to project records.
- `explain` answers what a path or symbol does and why it exists.
- `context` builds a compact evidence bundle for a task.
- `impact` shows the code and records affected by a change.
- `reflect` proposes new or updated records after work is completed.
- `validate` detects broken links, stale records, and contradictory active constraints.
- `doctor` verifies that configuration, records, index, and validation are ready.

## Onboard an existing codebase

Run one command when a repository has code but little reliable project reasoning:

```bash
whyloom onboard --root . --json
```

This initializes and indexes the repository, writes a stratified evidence manifest
and structural coverage ledger,
and records a pending agent request under `.whyloom/cache/bootstrap/`. The
installed Whyloom skills detect the request, inspect the evidence, and create
proposed records with explicit confidence, citations, and open questions. They
then validate, re-index, and mark onboarding complete.

Virtual environments and dependency caches—including named environments such as
`.venv-deepeval-cli`—are pruned from both the graph and onboarding evidence.
Structured configuration discovery is intentionally bounded to root files and
common workflow, configuration, deployment, infrastructure, and template paths;
projects can extend the `include` patterns in `whyloom.yaml` when needed.

Check the lifecycle at any time:

```bash
whyloom onboard --status --root . --json
```

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
- project-wide Python calls, imports, inheritance, and references with provenance;
- JSON and YAML configuration-key extraction without storing configuration values;
- stable structural communities and missing-rationale coverage;
- typed links between records and implementation;
- incremental local indexing;
- full-text retrieval plus bounded graph traversal;
- `onboard`, `init`, `index`, `explain`, `context`, `impact`, `reflect`, and `validate` commands;
- a portable Claude Code/Codex-style skill that invokes the CLI;
- fixtures and an A/B evaluation against plain repository documentation.

The MVP does not include a hosted service, accounts, cross-repository knowledge, a web dashboard, automatic acceptance of agent-authored records, or enterprise governance.

## Repository documents

- [RATIONALE.md](RATIONALE.md) — why this should exist and how the hypothesis will be tested.
- [DESCRIPTION.md](DESCRIPTION.md) — users, workflows, requirements, and MVP boundaries.
- [STRUCTURE.md](STRUCTURE.md) — repository layout, graph model, components, and command contracts.

## Status

Beta CLI ready for real codebase pilots. The CLI initializes a repository, parses canonical records,
indexes project-wide Python and structured configuration relationships into SQLite,
groups implementation into deterministic structural communities, retrieves bounded task context,
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

For agent calls, add `--compact` to `context` to return governing records,
relevant files and symbols, relationship provenance, communities, warnings, and unresolved questions.

See [docs/PRODUCTION_READINESS.md](docs/PRODUCTION_READINESS.md) for guarantees,
release gates, and explicit beta limits.

The [Structural Graph v2 dogfood report](docs/STRUCTURAL_GRAPH_V2_DOGFOOD.md)
shows the evidence chain recovered from a large existing codebase.
