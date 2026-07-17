# NODE-003 Verification

Node: Expose bootstrap through the Whyloom CLI
Verified: 2026-07-17T03:07:50.672Z

## Required evidence

- CLI tests cover human and JSON output without mutating canonical records.: satisfied
  - EVD-001 [command]: env PYTHONPATH=src /Users/rafael/Github/DataGeek/whyloom/.venv/bin/pytest -q tests/test_bootstrap.py::test_bootstrap_cli_emits_machine_readable_contract passed
    - Artifact: artifacts/EVD-001-command.json
