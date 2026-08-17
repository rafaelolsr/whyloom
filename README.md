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

The graph is the engine; governed rationale is the point. Whyloom's defining feature is that a record governs only when its claims are **grounded in verifiable code** — an inferred claim that resolves to nothing cannot become authoritative. Structural facts the code proves can govern automatically; the *why* behind a decision, which the code cannot prove, still requires a human. It runs on any folder and uses Git to enrich evidence when a repository is present, but Git is not required.

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

## How the value arrives

Whyloom is two layers, and they land at different times.

**Day zero — the deterministic graph.** Point Whyloom at a repository and index
it. `context`, `explain`, and `impact` work immediately, with **zero records and
no LLM**: ranked files and symbols for a task, the blast radius of a change, and
the structural role of any file. This layer is reproducible and fits in CI —
the same repository always yields the same graph. You get useful, auditable code
retrieval before writing a single record.

**Over time — the governed rationale.** The *why* is layered on top, and every
claim is anchored in code. It arrives two ways:

- **Inferred on request.** For an existing codebase, an installed agent skill
  reads the code and writes **grounded structural records** — a subsystem's role,
  boundaries, and relationships, each cited to real files. Because the code proves
  them, they govern immediately, with no human step. Any *why* the code does not
  record is surfaced as an open question, not asserted.
- **Captured from real work.** As decisions are made, `whyloom reflect` turns them
  into records during the pull request that made the change, while the reasoning
  is fresh — the *why* here carries a human's verification.

The distinguishing property is not "a human reviewed it" — it is that intent is
**verifiably grounded in the code**. A fabricated rationale resolves to nothing
and cannot govern; a structural fact the code proves governs on its own; and the
*why* the code cannot prove is answered by a human, never guessed. The memory a
team relies on is one whose every claim can be checked against the source.

## Quickstart

The minimal setup to get Whyloom working in a project — run these in order:

```bash
# Install the latest from source (recommended — always current):
uv tool install "git+https://github.com/rafaelolsr/whyloom.git@main#egg=whyloom[languages]"
# Public PyPI release (for environments that allow it):
# uv tool install "whyloom[languages]"
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
rationale drafted from existing code comments — surfaced in `context` results.
A claim governs only where it resolves to real code; an inference that grounds in
nothing is never treated as authoritative.

`propose` drafts records from tagged comments (`WHY:`, `DECISION:`, `HACK:`).
Rationale in non-Python files is only extracted when the matching tree-sitter
grammar is installed — use the `[languages]` install above; without it, those
files still index but their comments are skipped with a `LANG002` note.

After this, your agent has the skill, an instruction-file pointer telling it to
query before editing and capture after, and an index that stays current. Each
step is explained below.

## Install

Install the isolated CLI from source (recommended — always the current release):

```bash
uv tool install "git+https://github.com/rafaelolsr/whyloom.git@main"
whyloom install
```

Where public PyPI is permitted, the published release also works:

```bash
uv tool install whyloom
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
and offline). From source:

```bash
uv tool install "git+https://github.com/rafaelolsr/whyloom.git@main#egg=whyloom[languages]"      # all grammars
uv tool install "git+https://github.com/rafaelolsr/whyloom.git@main#egg=whyloom[typescript,go]"  # or pick specific ones
```

Or, where public PyPI is permitted: `uv tool install "whyloom[languages]"`.

Without a grammar installed, files in that language are still recorded, with a
`LANG002` note that symbol extraction was skipped.

## Core workflow

```bash
whyloom onboard
whyloom index
whyloom explain src/auth/token_service.py
whyloom context "change refresh-token rotation"
whyloom impact decisions/0007-token-storage.md
whyloom path TokenService SessionStore
whyloom map --output graph.html
whyloom reflect "describe the durable project learning"
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
- `export graphml` / `export svg` write the graph as GraphML (for Gephi, yEd, NetworkX) or a static SVG image — both deterministic.
- `report` summarizes the graph: most-connected entities ("god nodes") and suggested starter questions, optionally to `GRAPH_REPORT.md`.
- `watch` re-indexes automatically as source files change (poll-based; an alternative to the commit hook during active development).
- `flow` traces the ordered execution skeleton from an entry point — the call sequence that answers "how does this work", deterministically.
- `propose` drafts decision records from in-code `WHY`/`DECISION`/`HACK` comments — the author's own words, captured for a human to confirm.
- `hook install` adds a local Git post-commit hook so the graph stays fresh automatically; it works with any remote, including GitHub, GitLab, and Azure DevOps. Use `hook azure` for a server-side Azure Pipelines snippet.
- `reflect` drafts a rationale record after work is completed, requiring every claim to cite the changed code; anything it cannot ground becomes an open question. It also surfaces precedent — previously reviewed decisions covering the same ground (including reversed ones) — so a new draft links or supersedes instead of duplicating.
- `accept` records a human verification (bulk with `--all`) — needed for a *decision's* why; a grounded structural record governs without it.
- `learnings` reports rationale gaps (source files with no governing record) so the capture loop stays reliable; add `--changed` to scope it to recent work.
- `usage` reports how many queries the graph answered (per command) — concrete proof the agent is using the graph instead of grep.
- `validate` detects broken links, stale records, contradictory active constraints, and same-type records claiming the same scope without a supersession link.
- `doctor` verifies that configuration, records, index, and validation are ready.
- `mcp` serves the read-only query surface (`context`, `explain`, `impact`, `path`, `flow`) over MCP stdio for Claude Desktop, Cursor, Windsurf, and VS Code — same payloads as `--json`. Writing stays in the CLI so human review is never bypassed. Requires `pip install "whyloom[mcp]"`.

## Onboard an existing codebase

Run one command when a repository has code but little reliable project reasoning:

```bash
whyloom onboard --root . --json
```

This initializes and indexes the repository, writes a stratified evidence manifest
and structural coverage ledger,
and records a pending agent request under `.whyloom/cache/bootstrap/`. The
installed Whyloom skills detect the request, inspect the evidence, and write
**grounded structural records** — each claim cited to real code, so they govern
without a human — plus open questions for any *why* the code does not record. They
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

Inferred structural records govern only where their claims resolve to real code (`TRUST002`). Any *why* the code does not record is left as an open question for a human — never asserted as a decision.

## Trust model

A record governs by **two rules**:

1. **Grounding.** Every claim must cite verifiable code — a `targets` path or an
   `evidence` source that resolves to a real file or symbol. A governing record
   that cites nothing checkable is invalid (`TRUST002`). Trust is *consistency
   with the code*, not a signature — so a fabricated rationale, which resolves to
   nothing, cannot govern.

2. **Verification, by the right kind of author.** What the code *is* (a
   subsystem's role, its boundaries, what calls what) is provable from evidence,
   so a **grounded structural record may be verified by a process** (e.g. an
   onboarding agent) and govern with no human step. What the code *is for* — the
   *why* a decision was made — is **not** in the code; inferring it is guesswork,
   so a decision or constraint requires a **human** verifier (`TRUST001`).

The practical consequence:

| Record | Anchored in | Who verifies it |
|---|---|---|
| Architecture / role — *what the code is* | structure (imports, calls, containment) | a process or a human — governs on evidence |
| Decision / constraint — *why it is so* | a documented choice, or a human | a human, always |

An agent can therefore onboard a codebase and make its **structure** governing on
its own, while the **why** it cannot ground is surfaced as an open question for a
human to answer — never asserted. The other truths are unchanged: code is the
source of truth for implementation, tests for behavior, and the generated index
is a cache, never an authority.

Records are Markdown, so review is your normal pull-request review. `whyloom
reflect` captures rationale from real work; `whyloom accept` records a human
verification from the CLI when you want it — but a grounded structural record
does not wait on it.

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
