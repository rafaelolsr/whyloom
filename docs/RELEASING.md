# Releasing Whyloom

Whyloom publishes Python distributions through PyPI Trusted Publishing. No
long-lived PyPI token belongs in GitHub secrets.

## One-time PyPI setup

1. Sign in to PyPI and create a pending trusted publisher for package `whyloom`.
2. Set owner to `rafaelolsr` and repository to `whyloom`.
3. Set workflow to `release.yml` and environment to `pypi`.
4. In GitHub, create the `pypi` environment and restrict it to release tags or
   require approval if desired.

## Release

1. Update the version in `pyproject.toml`, `src/whyloom/__init__.py`, and `uv.lock`.
2. Run the complete release gate from `docs/PRODUCTION_READINESS.md`.
3. Push the version commit and create a GitHub release whose tag matches it.
4. The release workflow builds once, preserves the distributions as an artifact,
   and publishes the same files to PyPI with GitHub OIDC.
5. Verify `uv tool install whyloom` in a clean environment before announcing the release.
