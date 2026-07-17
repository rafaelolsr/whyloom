# NODE-013 Verification

Node: Implement shared dependency directory pruning
Verified: 2026-07-17T14:02:43.112Z

## Required evidence

- Named virtual environment regression tests pass.: satisfied
  - EVD-001 [manual]: Regression tests exclude suffixed virtual environments, venv-local, .tox, node_modules, and nested site-packages from index and evidence; read-only StarBase scan found 1,055 project Python files and zero leaked dependency files.
    - Artifact: artifacts/EVD-001-test_bootstrap.py
