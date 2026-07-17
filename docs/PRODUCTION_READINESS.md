# Production-readiness contract

Whyloom `0.2` is intended for real codebase pilots as a local CLI.

## Guarantees

- Configuration and record paths cannot escape the repository.
- Invalid records abort indexing before graph sources are changed.
- Read commands never create a missing index and return stable JSON errors.
- Indexing honors configured include and exclude patterns.
- SQLite uses a busy timeout and WAL mode for normal concurrent readers.
- Schema and index-format versions migrate storage and force semantic reindexing after extractor changes.
- Reflection includes tracked and untracked changed files and always proposes.
- `doctor` checks configuration, records, index presence, and validation state.
- CI tests Python 3.11–3.13, builds distribution artifacts, self-indexes, runs
  doctor, and executes the comparison evaluation.

## Explicit limits

- Python is the only code extractor.
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
uv run whyloom index --json
uv run whyloom validate --json
uv run whyloom doctor --json
uv run python evals/runner.py
```

All commands must succeed from a clean checkout.
