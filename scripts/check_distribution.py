from __future__ import annotations

import sys
import zipfile
from pathlib import Path

REQUIRED_SUFFIXES = {
    "share/whyloom/skills/whyloom/SKILL.md",
    "share/whyloom/skills/whyloom/agents/openai.yaml",
    "share/whyloom/skills/whyloom-bootstrap/SKILL.md",
    "share/whyloom/skills/whyloom-bootstrap/agents/openai.yaml",
}


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: check_distribution.py <wheel>", file=sys.stderr)
        return 2
    wheel = Path(sys.argv[1])
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    missing = sorted(suffix for suffix in REQUIRED_SUFFIXES if not any(name.endswith(suffix) for name in names))
    if missing:
        print(f"wheel is missing bundled skill resources: {', '.join(missing)}", file=sys.stderr)
        return 1
    print(f"distribution valid: {wheel}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
