# Security policy

Whyloom is a local CLI. It reads repository files selected by `whyloom.yaml`
and writes its generated SQLite cache beneath the configured repository-relative
database path.

## Supported versions

Security fixes are applied to the latest `0.x` release while the project is in
beta.

## Reporting

Do not place vulnerability details in a public issue. Contact the repository
owner privately until a dedicated security-reporting address is published.

## Trust boundaries

- Treat repository contents and record YAML as untrusted input.
- Never store credentials, private prompts, or model chain-of-thought in records.
- Review reflection proposals before changing their status to accepted.
- Keep `.whyloom/` untracked; it is a generated cache.
- Run the CLI with the same filesystem permissions as the repository user.
