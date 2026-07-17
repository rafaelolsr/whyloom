# NODE-003 Evidence

Node: Expose bootstrap through the Whyloom CLI

## Items

- EVD-001 [command] satisfies `CLI tests cover human and JSON output without mutating canonical records.`: env PYTHONPATH=src /Users/rafael/Github/DataGeek/whyloom/.venv/bin/pytest -q tests/test_bootstrap.py::test_bootstrap_cli_emits_machine_readable_contract passed
  - Artifact: artifacts/EVD-001-command.json
