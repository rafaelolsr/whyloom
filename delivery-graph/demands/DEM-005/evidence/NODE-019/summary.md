# NODE-019 Evidence

Node: Validate Structural Graph v2 and dogfood StarBase

## Items

- EVD-001 [report] satisfies `Full release gate and StarBase GetDefinition acceptance check pass`: Whyloom 0.6.0 passes 38 tests, Ruff, both skill validators, wheel build/contents, self-index, validation, doctor, evaluation suite, and StarBase dogfood. The acceptance graph reconstructs GetDefinition -> Fabric POST -> auth headers -> Fabric token -> OBO exchange with extracted line evidence and an explicit missing-rationale warning.
  - Artifact: artifacts/EVD-001-STRUCTURAL_GRAPH_V2_DOGFOOD.md
