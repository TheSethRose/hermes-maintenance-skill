#!/usr/bin/env python3
"""Run exactly one due native Hermes maintenance segment from cron."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def build_command(home: Path) -> list[str]:
    runner = home / "skills" / "hermes-maintenance" / "scripts" / "hermes-maintenance.py"
    return [sys.executable, str(runner), "--mode", "native", "--next", "--apply"]


def main() -> int:
    home = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes")).expanduser().resolve()
    command = build_command(home)
    runner = Path(command[1])
    if not runner.is_file():
        print(f"Hermes maintenance runner not found: {runner}", file=sys.stderr)
        return 2

    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    stdout = completed.stdout.strip()
    if stdout and stdout != "HERMES_MAINTENANCE_COMPLETE":
        print(stdout)
    if completed.stderr:
        print(completed.stderr.rstrip(), file=sys.stderr)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
