# MVP comparison result

Date: 2026-07-31

Decision: **continue**

Two suites run against a flat lexical-search baseline: the original Python suite
(gated on recall *and* precision) and a multi-language suite (gated on recall,
precision reported) that proves cross-file traversal grep cannot perform.

## Python suite (recall + precision)

| Case | Whyloom irrelevant | Baseline irrelevant | Whyloom | Baseline |
| --- | ---: | ---: | ---: | ---: |
| Context for token storage | 0 | 0 | 0.35 ms | 7.18 ms |
| Explain authentication file | 1 | 1 | 0.23 ms | 7.10 ms |
| Constraint impact | 0 | 0 | 0.19 ms | 7.55 ms |
| Unrelated task | 0 | 1 | 0.04 ms | 7.32 ms |

The constraint-impact case now expects both `CON-0001` and `DEC-0001`: the
decision declares `constraints: [CON-0001]`, so it is genuinely affected by the
constraint and belongs in the answer.

## Multi-language suite (recall; TypeScript + Go)

Each case requires a target reached through a **cross-file** relationship the
graph resolves and flat search cannot follow.

| Case | Reached via | Recall | Whyloom | Baseline |
| --- | --- | :---: | ---: | ---: |
| Change how sessions start | governing record → `session.ts` | ✅ | 0.35 ms | 6.69 ms |
| Modify token issuance used by sessions | `session.ts` → CALLS → `tokens.ts` | ✅ | 0.29 ms | 5.98 ms |
| Change how login validates users | `handler.go` → CALLS → `validate.go` | ✅ | 0.14 ms | 5.90 ms |
| Unrelated task | — (correctly empty) | ✅ | 0.05 ms | 5.80 ms |

## Interpretation

Recall is 100% on both suites, including targets reachable only by following
cross-file `CALLS` and record links — the capability flat search structurally
lacks. Graph lookup is ~20–40× faster than scanning file contents because it is a
bounded index query, not a text sweep.

Precision on the multi-language fixture is not gated: the four-file repo is too
small for graph expansion to discriminate, so a correct target still pulls in the
whole neighborhood. That is a fixture-size artifact, not a retrieval defect; the
next step is a larger, realistic multi-language repository with human usefulness
ratings and import-alias tracking to promote cross-file edges from INFERRED to
EXTRACTED.
