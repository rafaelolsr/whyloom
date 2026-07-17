# MVP comparison result

Date: 2026-07-16

Decision: **continue**

All four starter cases returned the required governing records and code targets.
Whyloom introduced no more irrelevant evidence than flat repository search and
correctly returned an empty packet for an unrelated task.

| Case | Whyloom irrelevant | Baseline irrelevant | Whyloom retrieval | Baseline retrieval |
| --- | ---: | ---: | ---: | ---: |
| Context for token storage | 0 | 0 | 0.31 ms | 2.87 ms |
| Explain authentication file | 0 | 1 | 0.19 ms | 4.00 ms |
| Constraint impact | 0 | 0 | 0.15 ms | 3.63 ms |
| Unrelated task | 0 | 1 | 0.05 ms | 3.04 ms |

## Interpretation

The graph-backed lookup was faster and at least as precise on this tiny fixture,
but its JSON evidence packets were larger than the raw flat-search payloads.
This validates the structural retrieval loop, not production-scale usefulness.

The next evaluation should add a realistic repository, more ambiguous tasks,
human usefulness ratings, and a compact rendering mode before expanding beyond
Python.
