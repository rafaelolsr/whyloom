# Contributing

## Development setup

```bash
uv sync --extra dev
uv run ruff check .
uv run pytest -q
uv run whyloom index --json
uv run whyloom doctor --json
uv run python evals/runner.py
```

Add tests for behavior changes. Update canonical records when a change alters a
durable architectural decision or constraint. Agent-generated records must
remain proposed until reviewed.

Before opening a change, ensure the wheel builds:

```bash
uv build
```
