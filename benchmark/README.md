# Whyloom Copilot benchmark

Measure Whyloom's effect on GitHub Copilot CLI using **real logged data** —
Copilot records every session (tool commands, token usage, latency) in
`~/.copilot/session-store.db`. No Langfuse, no screenshots, no estimation.

## Why this exists

Copilot is a closed product: you can't pipe its calls to an external observability
platform. But it keeps a rich local SQLite log. This scorer reads it and compares
two runs of the same question — one with Whyloom available, one without — so you
get a cite-able number for an adoption case.

## How to run

1. In the target repo, make sure Whyloom is installed for Copilot:
   ```bash
   whyloom install --platform copilot --project
   ```

2. Run the question in Copilot **twice**, tagging each prompt:
   ```
   How does the advisor orchestrator work? [bench-with]
   ```
   Then disable Whyloom for the baseline (tell Copilot not to use it, or move the
   guidance/skill aside) and run:
   ```
   How does the advisor orchestrator work? [bench-without]
   ```

3. Score it:
   ```bash
   python benchmark/copilot_bench.py --repo StarBase
   ```

## Output

```
Whyloom Copilot benchmark
  question: 'How does the advisor orchestrator work?'

  metric                       without           with      delta
  LLM calls                          9              8       -11%
  Tool calls                        13              5       -62%
    · whyloom calls                  0              5
    · grep/read calls                8              0
  Context tokens (read)        980,000        630,000       -36%
  ...
  → Whyloom read -36% the context tokens to answer the same question.
```

## Notes

- **Context tokens** (input + cache-read) is the headline metric: it's what the
  model had to read to answer, which balloons when an agent greps and reads files
  instead of querying the graph.
- The scorer pairs runs by a **prompt tag** (`--with` / `--without`), taking the
  most recent session matching each. Use `--repo` to scope to one codebase.
- Everything is read-only against Copilot's own DB; it never writes to it.
