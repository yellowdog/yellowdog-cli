"""
Clear up after live system test runs that died: tear down every run that
left something behind and started more than --older-than hours ago (the
configuration's sweep_age_hours by default), or the runs named with --run.

    python tests/live/sweep.py [--older-than HOURS] [--run RUN_ID ...] [--dry-run]

Exits 0 when everything went, 1 when something could not be torn down, 2
for a configuration problem or a --run that is not a run ID.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from harness import data
from harness.config import LiveConfigError, load_live_config
from harness.lifecycle import sweep, teardown
from harness.run import Run, run_id_of
from harness.yd import Yd


def main(argv: list[str] | None = None, make_yd: Callable[[Run], Yd] = Yd) -> int:
    parser = argparse.ArgumentParser(
        prog="sweep.py", description="Tear down dead live system test runs."
    )
    parser.add_argument("--older-than", type=float, metavar="HOURS")
    parser.add_argument("--run", action="append", default=[], metavar="RUN_ID")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    for run_id in args.run:
        if run_id_of(run_id) != run_id:
            print(f"'{run_id}' is not a run ID", file=sys.stderr)
            return 2
    try:
        config = load_live_config()
    except LiveConfigError as error:
        print(error, file=sys.stderr)
        return 2

    settings = config.run
    hours = settings["sweep_age_hours"] if args.older_than is None else args.older_than
    timeout = settings["teardown_timeout_minutes"]
    with tempfile.TemporaryDirectory() as parent:
        # A run of its own for the CLI configuration only: it creates nothing
        run = Run.start(config, Path(parent))
        yd = make_yd(run)
        has_data = data.local_remote(config) is not None
        if args.run:
            problems: list[str] = []
            for run_id in args.run:
                print(
                    f"{'Would tear down' if args.dry_run else 'Tearing down'} run {run_id}"
                )
                if not args.dry_run:
                    problems += teardown(
                        yd, run.namespace, run_id, timeout, data=has_data
                    )
        else:
            problems = sweep(
                yd,
                run.namespace,
                timedelta(hours=hours),
                timeout,
                dry_run=args.dry_run,
                data=has_data,
            )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
