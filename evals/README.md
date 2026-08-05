# Whyloom evals

Repeatable A/B that scores graph retrieval against a lexical (grep-like) baseline
on fixed fixtures with known-correct answers. Run:

```bash
uv run python evals/runner.py
```

Each case is `task → expected_records + expected_targets`. The runner indexes the
fixture, runs `context_packet`, and reports recall, precision, and character cost
versus `flat_search` (the baseline).

## Suites

| Suite | Gate | Proves |
|---|---|---|
| `python` | recall + precision | Records and their targets surface for a task; precision beats the baseline. |
| `multi-language` | recall | Cross-file traversal across TS/Go/… that grep cannot do (skipped if tree-sitter grammars absent). |
| `zero-record-retrieval` | recall | The **day-zero graph** finds the right file with **no records at all**, through two ranking traps. |

## Ranking traps (zero-record suite)

These encode retrieval bugs found by real-repo benchmarking, so they cannot
regress silently:

- **Term-frequency trap** — a noise file that repeats a query word must not
  outrank the file whose path/name actually matches the task.
- **File-monopoly trap** — a symbol-dense file must not consume every result
  slot and bury a sparse-but-relevant sibling (fixed by deep over-fetch +
  per-file diversification, and by keeping that diversified order when
  `context_packet` selects seeds).

## Note on cost

Character/token savings appear at real-repo scale (finding one file vs. grepping
and reading thousands of lines). On these tiny fixtures the baseline reads only a
few small files, so the zero-record suite gates on **correctness**, not cost.
