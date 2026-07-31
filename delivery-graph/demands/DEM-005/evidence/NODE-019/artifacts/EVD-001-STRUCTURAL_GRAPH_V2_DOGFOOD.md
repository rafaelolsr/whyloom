# Structural Graph v2 dogfood

## Acceptance repository

Structural Graph v2 was exercised against `StarBaseAIAssistant`, a large existing
Python codebase with deployment configuration and pre-existing Whyloom records.
The bounded run indexed 1,137 implementation and configuration files, assigned
all 1,137 files to 28 deterministic structural communities, and reported 25
communities without linked rationale.

## Acceptance question

> What implementation fixes GetDefinition access to Microsoft Fabric, and where
> is it implemented?

Whyloom returned an evidence-backed implementation path without claiming that an
accepted rationale record exists:

1. `FabricReportFetcher._fetch_via_get_definition` calls `_fabric_post` at
   `src/services/fabric_report_fetcher.py:680`.
2. `_fabric_post` calls `_fabric_headers_and_session` at
   `src/services/fabric_report_fetcher.py:550`.
3. `_fabric_headers_and_session` calls `AzureAuthService.get_fabric_token` at
   `src/services/fabric_report_fetcher.py:499`.
4. `AzureAuthService.get_fabric_token` calls `exchange_obo_token` at
   `src/services/azure_auth.py:525`.

Every relationship was returned as an extracted `CALLS` edge with source-line
evidence. Whyloom also returned the warning that no accepted decision or
constraint governs the task.

## Failure modes found while dogfooding

- Broad recursive JSON discovery included generated caches and artifact data.
  Default discovery now targets root, workflow, configuration, deployment,
  infrastructure, and template surfaces while pruning shared cache directories.
- Generic configuration names initially produced excessive inferred links.
  Configuration-to-code inference now requires distinctive identifiers and a
  bounded target set.
- Breadth-first traversal exhausted its budget on adjacent nodes before reaching
  the authentication chain. Retrieval now uses relevance-ranked seeds and
  best-first weighted traversal, preferring high-signal call paths.

## Result

The acceptance case passes: the generated graph reconstructs the implementation
path, cites the source lines, distinguishes extracted from inferred evidence, and
preserves missing rationale as an explicit knowledge gap for onboarding.
