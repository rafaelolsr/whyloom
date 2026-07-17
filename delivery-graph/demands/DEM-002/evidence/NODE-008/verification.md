# NODE-008 Verification

Node: Add trusted PyPI release workflow and metadata
Verified: 2026-07-17T12:16:23.140Z

## Required evidence

- Build succeeds and release workflow declares OIDC permissions and PyPI publish action.: satisfied
  - EVD-001 [command]: env PYTHONPATH=src /Users/rafael/Github/DataGeek/whyloom/.venv/bin/pytest -q tests/test_release_contract.py passed
    - Artifact: artifacts/EVD-001-command.json
