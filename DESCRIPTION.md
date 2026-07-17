# Product description

## Definition

Whyloom is a codebase-scoped project memory that lets humans and coding agents recover the meaning behind an implementation. It stores reviewed project records in Git, connects them to code in a generated local graph, and retrieves a compact explanation for the task currently being performed.

## Primary users

- developers resuming work in an unfamiliar or long-running area;
- coding agents planning or implementing repository changes;
- maintainers reviewing whether a change preserves project intent;
- teams onboarding contributors without replaying old conversations;
- incident responders tracing why safeguards and workarounds exist.

## Jobs to be done

### Explain an implementation

Given a file or symbol, return its architectural role, governing decisions, active constraints, related incidents, and supporting evidence.

### Prepare an agent for a task

Given a task statement, retrieve the smallest connected set of code and accepted rationale that the agent should understand before acting.

### Evaluate change impact

Given a decision, constraint, file, or symbol, identify connected implementation and records that may need review.

### Preserve new project learning

After an agent or human completes work, produce reviewable proposals for decisions, constraints, incident lessons, or supersession links discovered during the task.

### Bootstrap an existing codebase

Index the configured source graph, collect bounded evidence from documentation,
tests, configuration, dependencies, rationale comments, and local Git history,
then let an agent propose a small set of confidence-labeled records for human
review. Evidence describes what can be observed; inferred intent never becomes
authoritative automatically.

### Protect the source of truth

Validate record schemas, targets, lifecycle status, broken links, conflicting active constraints, and likely drift between records and the current code.

## Canonical knowledge model

Project records use Markdown for readable content and YAML frontmatter for machine-readable identity and links.

Initial record types:

- **Decision:** a chosen approach, its rationale, alternatives, consequences, and status.
- **Constraint:** a technical, product, security, regulatory, or operational condition that must remain true.
- **Architecture:** stable subsystem responsibilities and boundaries.
- **Incident:** a failure, its cause, remediation, and lessons that should constrain future work.
- **Glossary:** project-specific terms and canonical meanings.

Lifecycle states:

```text
draft → proposed → accepted → implemented
                    ↘ superseded | rejected | expired
```

Only accepted or implemented records govern normal retrieval by default. Other states remain visible when explaining history or resolving conflicts.

## Functional requirements

### Initialization

- add a standard `whyloom/` record directory and templates;
- add local generated-state paths to `.gitignore`;
- avoid overwriting existing project files;
- produce a valid starter overview and configuration.

### Indexing

- scan supported source files and project records;
- extract files, symbols, imports, definitions, and explicit record targets;
- write nodes and edges to a local SQLite store;
- use content hashes to update only changed inputs;
- retain provenance and confidence for every generated relationship.

### Retrieval

- combine lexical retrieval with typed, bounded graph traversal;
- prioritize accepted, recent, directly linked evidence;
- return a token-bounded context package with citations to repository paths;
- expose why each item was included;
- report unresolved references and missing rationale.

### Reflection

- inspect the task summary, diff, and existing records;
- propose concise new or updated records;
- mark generated output as proposed;
- require normal human review before acceptance.

### Validation

- validate record schemas and unique identifiers;
- detect missing targets and broken references;
- detect impossible lifecycle or supersession relationships;
- flag conflicting accepted constraints;
- flag records whose linked code has materially changed since evidence was recorded.

### Integration

- provide a stable CLI and JSON output;
- ship a portable skill for Claude Code and Codex-style agents;
- keep a future MCP adapter possible without coupling the core to a specific agent.
- ship a separate `whyloom-bootstrap` skill for one-time existing-repository onboarding.

## MVP user journey

1. A maintainer runs `whyloom init` in an existing repository.
2. They add two decisions and two constraints using generated templates.
3. `whyloom index` connects those records to files and symbols.
4. A coding agent receives a task and calls `whyloom context`.
5. The agent plans and implements using the returned evidence.
6. `whyloom reflect` proposes any new project learning.
7. A human reviews the proposal in Git.
8. `whyloom validate` confirms the knowledge graph remains coherent.

## Non-goals for the MVP

- general enterprise knowledge management;
- organization-wide or cross-repository search;
- replacing source code, tests, issue trackers, or Git history;
- storing full agent conversations or private reasoning traces;
- autonomous architectural governance;
- cloud synchronization, permissions, billing, or collaboration UI;
- embedding every file by default;
- generating a complete knowledge graph before returning value.
