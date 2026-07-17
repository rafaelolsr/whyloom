# MVP evaluation contract

Whyloom uses this repository as its first reference codebase. Python is the
first supported language because its standard AST provides deterministic,
line-level symbols and imports without a compiled runtime dependency.

## Claim

For code changes governed by recorded decisions or constraints, a lexical
candidate search followed by bounded graph traversal returns the expected
evidence with less irrelevant text than flat Markdown search.

## Conditions

1. **Baseline:** search ordinary repository Markdown and source text.
2. **Whyloom:** index records and code, then call `whyloom context --json`.

## Required measurements

- expected record recall;
- expected target-file recall;
- irrelevant evidence count;
- returned character count as a deterministic token proxy;
- elapsed retrieval time;
- broken-constraint warnings;
- human-rated usefulness on a 1–5 rubric.

## Continuation threshold

Continue after the MVP if all starter cases return their expected governing
records and files, validation catches the seeded broken-link fixture, and the
Whyloom packet contains no more irrelevant items than the flat-search baseline.

## Reference repository

The Whyloom repository is the reference implementation. Tests also use a small
synthetic Python project under `tests/fixtures/sample_repo` so expected graph
nodes and edges remain stable.

