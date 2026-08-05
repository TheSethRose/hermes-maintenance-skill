#!/usr/bin/env python3
"""Bridge Hermes cron containment to the installed maintenance skill."""

from __future__ import annotations

import os
import runpy
from pathlib import Path


def wrapper_path(home: Path) -> Path:
    return home / "skills" / "hermes-maintenance" / "scripts" / "hermes-maintenance-cron.py"


def main() -> int:
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()
    target = wrapper_path(home)
    if not target.is_file():
        print(f"Installed Hermes maintenance cron wrapper not found: {target}")
        return 2
    try:
        runpy.run_path(str(target), run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
