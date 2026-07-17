# NODE-013 Evidence

Node: Implement shared dependency directory pruning

## Items

- EVD-001 [manual] satisfies `Named virtual environment regression tests pass.`: Regression tests exclude suffixed virtual environments, venv-local, .tox, node_modules, and nested site-packages from index and evidence; read-only StarBase scan found 1,055 project Python files and zero leaked dependency files.
  - Artifact: artifacts/EVD-001-test_bootstrap.py
