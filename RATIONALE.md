# Project rationale

## Why now

Coding agents increasingly produce not only code but also architectural choices, trade-offs, workarounds, and operational decisions. Those decisions are usually trapped in transient conversations. As a project grows, future humans and agents inherit the implementation without the reasoning that shaped it.

This creates a compounding failure mode:

1. an agent makes a locally reasonable decision;
2. the reasoning is lost after the task or conversation is compacted;
3. a later agent reconstructs intent from code and nearby text;
4. it repeats rejected work, violates a constraint, or creates a conflicting design;
5. the new reasoning is lost again.

Whyloom turns that lossy cycle into a reviewed feedback loop.

## Core hypothesis

For a single codebase, a Git-versioned graph that connects implementation to accepted decisions and constraints can provide more precise and faster task context than large context windows, flat documentation, or semantic search alone.

The graph matters because project knowledge is relational:

- a decision applies to particular files and symbols;
- a constraint limits several decisions;
- a newer decision supersedes an older one;
- an incident motivates a safeguard;
- a subsystem implements an architectural responsibility.

Flat search can find individually related documents. Graph traversal can assemble the small connected explanation needed for the current task.

## Product principles

### Repository-native

Canonical knowledge lives beside the code, is reviewed through Git, and evolves through normal pull requests.

### Local-first

The index is fast, private, and rebuildable. The MVP requires no hosted service.

### Evidence over confidence

Every explanation identifies the records, files, and links that support it. Missing evidence is reported as missing rather than filled with plausible prose.

### Human-governed memory

Agents may propose project knowledge but cannot silently promote it to accepted truth.

### Task-specific retrieval

The output is a bounded context package for a concrete task, not a dump of everything that shares keywords.

### Minimal ceremony

Records must be concise enough to maintain. Whyloom should generate templates, suggest links, and validate structure without requiring a documentation program.

## Why this is not just documentation

Documentation explains topics. Whyloom also models typed relationships, temporal status, evidence, and implementation coverage. It can answer questions that require crossing those relationships:

- What decision governs this symbol?
- Which active constraint would this change violate?
- What replaced the old approach?
- What code is likely affected if this decision changes?
- Which parts of the implementation have no recorded rationale?

## Why this is not just code search

Code search explains implementation proximity. Whyloom introduces project meaning that may not be present in the source: rejected alternatives, business constraints, incident lessons, ownership, and supersession.

## Validation criteria

The MVP is worth continuing if, on a small real repository:

- an agent reaches relevant rationale with fewer files and fewer tokens;
- task-context bundles contain the expected governing decisions and constraints;
- developers judge explanations as more actionable than plain documentation retrieval;
- the tool prevents at least one realistic constraint violation or repeated rejected approach;
- indexing remains fast enough to run routinely after changes;
- maintaining records feels proportional to the value received.

The initial evaluation should compare the same tasks under two conditions:

1. repository plus ordinary Markdown documentation;
2. repository plus Whyloom records and graph retrieval.

Measure task completion, violations of known constraints, irrelevant context, tokens consumed, time to first correct plan, and human-rated explanation quality.

## Primary risks

- **Stale rationale:** records can drift from implementation.
- **Capture burden:** developers may not maintain a system that demands excessive ceremony.
- **False authority:** generated or speculative text may be mistaken for accepted truth.
- **Graph noise:** weak automatic links may reduce precision.
- **Bootstrapping:** an existing project may lack enough recorded reasoning to be immediately useful.
- **Agent dependence:** different coding agents expose different integration surfaces.

The MVP addresses these with explicit status, evidence links, Git review, narrow node and edge types, validation rules, confidence labels for inferred links, and a CLI-first integration boundary.

