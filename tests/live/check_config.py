"""
Check the live system tests' configuration without running anything: load
it as a run does (YDST_CONFIG, else ~/.config/yellowdog/system-tests.toml,
then the YDST_<SECTION>_<KEY> overrides) and report it, touching neither the
Platform nor any cloud.

    python tests/live/check_config.py

Prints the summary a session starts with and any warnings (retired keys),
and exits 0; or lists every problem on stderr and exits 2. No secret value
is ever printed.
"""

from __future__ import annotations

import sys

from harness.config import LiveConfigError, load_live_config


def main() -> int:
    try:
        loaded = load_live_config()
    except LiveConfigError as error:
        print(error, file=sys.stderr)
        return 2
    print(loaded.summary())
    for warning in loaded.warnings:
        print(f"live config: warning: {warning}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
