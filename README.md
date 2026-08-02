<div align="center">

<img src="docs/assets/whyloom-banner.png" alt="Whyloom — weave code and its reasoning into one graph" width="100%">

# Whyloom

**Your codebase remembers why.** *Trusted project memory for coding agents — a deterministic code-knowledge graph that links every file and symbol to the decisions, constraints, and rejected alternatives that explain it, and serves fast, task-specific, auditable context.*

[![CI](https://github.com/rafaelolsr/whyloom/actions/workflows/ci.yml/badge.svg)](https://github.com/rafaelolsr/whyloom/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/whyloom.svg)](https://pypi.org/project/whyloom/)
[![Python](https://img.shields.io/pypi/pyversions/whyloom.svg)](https://pypi.org/project/whyloom/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Works with **Claude Code · Codex · GitHub Copilot · Agent Skills** — one deterministic CLI, portable skills, a tiny dependency surface, and nothing that leaves your machine. Indexes **Python, TypeScript, JavaScript, Go, Rust, Java, and C#**. No LLM in the pipeline; runs on any folder, with or without Git.

[Install](#install) · [Core workflow](#core-workflow) · [Onboard a codebase](#onboard-an-existing-codebase) · [Trust model](#trust-model) · [How it works](STRUCTURE.md) · [Docs](#repository-documents)

</div>

---

## What is Whyloom?

Whyloom is trusted project memory for a codebase. It builds a deterministic, multi-language knowledge graph of your files and symbols, then links that implementation to the decisions, constraints, rejected alternatives, and operational lessons that explain it — so humans and coding agents get fast, task-specific context they can audit and rely on.

The graph is the engine; governed rationale is the point. Whyloom's defining feature is that nothing an LLM inferred becomes authoritative until a human accepts it in review — the map is generated automatically, but the *why* is trusted only after human sign-off. It runs on any folder and uses Git to enrich evidence when a repository is present, but Git is not required.

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

1. **Canonical project records** — concise Markdown records for decisions, constraints, architecture, incidents, and terminology, versioned alongside your code.
2. **A generated local graph** — files and symbols across seven languages, configuration keys, structural
   communities, records, and typed cross-file relationships (calls, imports, inheritance) indexed for fast, bounded traversal.

Your source files and records remain the source of truth. The graph is a disposable cache and can always be rebuilt.

```text
Code + project records
        ↓
Incremental indexer
        ↓
Local rationale graph
        ↓
Task-specific context for humans and agents
```

## Quickstart

The minimal setup to get Whyloom working in a project — run these in order:

```bash
uv tool install "whyloom[languages]"   # CLI + tree-sitter grammars (or plain `whyloom` for Python-only)
cd /your/project
whyloom install --project              # register the skill + add the agent-instruction pointer
whyloom onboard --root .               # initialize records and build the first index
whyloom propose                        # draft reviewable rationale from WHY/DECISION comments
whyloom hook install                   # keep the graph fresh on every commit
whyloom map --output graph.html        # a browsable HTML view of the graph
whyloom export obsidian                # an Obsidian vault of the code-and-rationale graph
whyloom doctor                         # confirm the setup is ready (integrity, index, freshness)
```

Day one you already get a queryable graph, an HTML map, an Obsidian vault, and
*proposed* rationale drafted from existing code comments — visible in `context`
results but clearly marked unreviewed. Nothing an inference produced is treated
as authoritative until you accept it.

After this, your agent has the skill, an instruction-file pointer telling it to
query before editing and capture after, and an index that stays current. Each
step is explained below.

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

When you install into a project, Whyloom also adds a short pointer to your
assistant's instruction file so the agent reliably runs the query/capture loop —
skill auto-matching alone is probabilistic. The file is chosen per platform:

| Platform | Instruction file |
|---|---|
| Claude | `CLAUDE.md` |
| Codex / Agents | `AGENTS.md` |
| GitHub Copilot | `.github/copilot-instructions.md` |

The pointer is a delimited, idempotent block: it never overwrites your own
content, and `whyloom uninstall --project` removes only that block. Opt out with
`whyloom install --project --no-guidance`.

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

Python works out of the box. To index the other languages, add the matching
tree-sitter grammar extra (they stay optional so the base install remains tiny
and offline):

```bash
uv tool install "whyloom[languages]"                 # all supported grammars
uv tool install "whyloom[typescript,go]"             # or pick specific ones
```

Without a grammar installed, files in that language are still recorded, with a
`LANG002` note that symbol extraction was skipped.

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
whyloom path TokenService SessionStore
whyloom map --output graph.html
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
- `path` traces the shortest relationship path between two entities, hop by hop, and can route through governing decisions and constraints — not just code.
- `map` renders the current graph as a self-contained, offline HTML view you can open in any browser — governed records highlighted, inferred edges distinguished.
- `export obsidian` writes an Obsidian-compatible vault of linked Markdown notes so you can browse the code-and-rationale graph in Obsidian's graph view.
- `propose` drafts reviewable, proposed decision records from in-code `WHY`/`DECISION`/`HACK` comments so a freshly onboarded repo has queryable rationale on day one — never accepted automatically.
- `hook install` adds a local Git post-commit hook so the graph stays fresh automatically; it works with any remote, including GitHub, GitLab, and Azure DevOps. Use `hook azure` for a server-side Azure Pipelines snippet.
- `reflect` proposes new or updated records after work is completed.
- `learnings` reports pending proposals and rationale gaps (source files with no governing record) so the capture loop stays reliable; add `--changed` to scope it to recent work.
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
- agent-generated knowledge enters as a proposal and requires normal human review before becoming accepted truth.

Whyloom stores concise rationale and evidence, not private model chain-of-thought.

## MVP

The first release proves one claim:

> Linking decisions and constraints directly to code through a local graph gives agents more useful context, faster, than reading undifferentiated documentation.

The MVP includes:

- Markdown records with YAML frontmatter;
- nodes for files, symbols, decisions, and constraints;
- deterministic symbol extraction for Python, TypeScript, JavaScript, Go, Rust, Java, and C# (Python via the standard AST; the rest via optional tree-sitter grammars);
- cross-file calls, imports, and inheritance with explicit `EXTRACTED`/`INFERRED` provenance;
- tagged in-code comments (`WHY`, `HACK`, `TODO`, ...) captured as queryable rationale nodes, ranked as advisory evidence beneath governed records;
- JSON and YAML configuration-key extraction without storing configuration values;
- stable structural communities and missing-rationale coverage;
- typed links between records and implementation;
- incremental local indexing that works with or without Git;
- full-text retrieval plus bounded graph traversal;
- shortest-path tracing between any two entities, routing through code *and* governing records;
- `onboard`, `init`, `index`, `explain`, `context`, `impact`, `path`, `reflect`, and `validate` commands;
- a portable Claude Code/Codex-style skill that invokes the CLI;
- fixtures and an A/B evaluation against plain repository documentation.

The MVP does not include a hosted service, accounts, cross-repository knowledge, a web dashboard, automatic acceptance of agent-authored records, or enterprise governance.

## Repository documents

- [RATIONALE.md](RATIONALE.md) — why this should exist and how the hypothesis will be tested.
- [DESCRIPTION.md](DESCRIPTION.md) — users, workflows, requirements, and MVP boundaries.
- [STRUCTURE.md](STRUCTURE.md) — repository layout, graph model, components, and command contracts.

## Status

Beta CLI ready for real codebase pilots. The CLI initializes a project, parses canonical records,
indexes seven-language symbol graphs with cross-file calls, imports, and inheritance plus structured
configuration relationships into SQLite, groups implementation into deterministic structural communities,
retrieves bounded task context, explains targets, traces impact and shortest paths, validates record drift,
and creates human-governed reflection proposals. The included skill and evaluation fixture exercise the
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
