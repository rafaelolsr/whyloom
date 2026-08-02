# Production-readiness contract

Whyloom `0.6.0` is intended for real codebase pilots as a local CLI.

## Guarantees

- Configuration and record paths cannot escape the repository.
- Invalid records abort indexing before graph sources are changed.
- Read commands never create a missing index and return stable JSON errors.
- Indexing honors configured include and exclude patterns.
- SQLite uses a busy timeout and WAL mode for normal concurrent readers.
- Concurrent index writes are serialized by an advisory file lock that
  self-heals a stale lock left by a crashed process, so a manual index and a
  commit hook cannot corrupt the graph by racing.
- A corrupt index is detected and surfaced as a clean `IDX003` error and a failed
  `doctor` integrity check, never an uncaught exception.
- `context`, `explain`, `impact`, and `path` warn when an indexed source no
  longer matches the working tree, so an agent never silently acts on a stale
  graph; `doctor` reports the same freshness state.
- Retrieval is bounded by `max_items` and stays low-single-digit-millisecond
  regardless of repository size (measured ~2.5 ms at 2,000 files, ~4.5 ms at
  4,000). Indexing reads each source once; cold onboarding is a one-time linear
  cost (~4–5 ms per file), and incremental reindex on a commit hook is
  sub-second for thousands of files. See `scripts/benchmark_scale.py`.
- Schema and index-format versions migrate storage and force semantic reindexing after extractor changes.
- Project-wide Python resolution records calls, inheritance, imports, and
  references with explicit provenance.
- Additional languages (TypeScript, JavaScript, Go, Rust, Java, C#) extract
  symbols through optional tree-sitter grammars and resolve cross-file calls and
  inheritance by symbol name as INFERRED edges; missing grammars degrade to a
  File node plus a LANG002 warning rather than failing the index.
- JSON and YAML adapters record key structure but never configuration values.
- Every indexed implementation file is assigned to a deterministic structural community.
- Reflection includes tracked and untracked changed files and always proposes.
- Bootstrap scans at most 20,000 files, stratifies the configured evidence
  budget across discovered categories, reports structural coverage, skips
  generated and dependency directories, and never edits canonical records.
- Bootstrap inference metadata remains non-governing until a human changes the
  record lifecycle status through normal Git review.
- Onboarding is idempotent, records a machine-readable pending request, exposes
  that lifecycle through indexing, and refuses completion until valid project
  memory exists.
- Code discovery and bootstrap evidence prune virtual environments, dependency
  caches, generated build trees, and nested `site-packages` directories before
  parsing files.
- Skill installation is idempotent, marks owned directories, and refuses to
  overwrite or remove unowned or symlinked skill directories.
- Distribution artifacts bundle both skills for offline registration after the
  Python package is installed.
- `doctor` checks configuration, records, index presence, and validation state.
- CI tests Python 3.11–3.13, builds distribution artifacts, self-indexes, runs
  doctor, and executes the comparison evaluation.

## Explicit limits

- Python has the most complete extractor (import-alias-aware call, inheritance,
  and reference resolution). TypeScript, JavaScript, Go, Rust, Java, and C# are
  supported through optional tree-sitter grammars with name-based cross-file
  resolution only; import aliases are not yet tracked, so their CALLS/INHERITS
  edges are INFERRED and lose confidence when a name is ambiguous. Cross-language
  edges are out of scope. JSON and YAML are indexed as configuration structure.
- Bootstrap discovers documentation, tests, configuration, dependencies,
  rationale comments, and Git subjects across common repository layouts, but
  semantic inference is performed by the portable skill rather than the CLI.
- Whyloom is scoped to one repository and one local SQLite index.
- Retrieval is lexical plus graph traversal; embeddings are not included.
- The evidence packet is advisory and must be verified against cited files.
- A public license and security contact still require owner decisions before a
  public release.

## Release gate

Run:

```bash
uv run pytest -q
uv run ruff check .
uv build
uv run python scripts/check_distribution.py dist/*.whl
uv run whyloom index --json
uv run whyloom validate --json
uv run whyloom doctor --json
uv run python evals/runner.py
```

All commands must succeed from a clean checkout.
