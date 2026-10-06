#!/usr/bin/env python3

"""
Copy files or directories between remote data client locations.

The source is checked before anything is copied: it must exist, a
directory needs --recursive (or --sync, which implies it), and --sync,
which deletes at the destination, is refused for a single file and for a
destination that is a remote's root or the configured bucket itself.
"""

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    config_remote_stat,
    copy_remote,
    record_transfer,
    resolve_remote_path,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.lazy import lazy
from yellowdog_cli.utils.load_config import (
    load_config_data_client,
    load_config_data_client_for_profile,
)
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone

CONFIG_SRC: ConfigDataClient = lazy(load_config_data_client)
CONFIG_DST: ConfigDataClient = lazy(
    lambda: load_config_data_client_for_profile(
        ARGS_PARSER.dst_profile,
        ARGS_PARSER.dst_prefix,
    )
)


@dataclient_wrapper
def main():
    if ARGS_PARSER.upgrade_rclone:
        upgrade_rclone()
        return

    if ARGS_PARSER.which_rclone:
        which_rclone()
        return

    # Both paths are given: the command line refuses otherwise
    src_path = resolve_remote_path(CONFIG_SRC, relative_path=ARGS_PARSER.src_path)
    dst_path = resolve_remote_path(CONFIG_DST, relative_path=ARGS_PARSER.dst_path)

    sync = ARGS_PARSER.sync or False
    recursive = bool(ARGS_PARSER.recursive) or sync  # --sync implies --recursive

    stat = config_remote_stat(CONFIG_SRC, src_path)
    if stat is None:
        raise FileNotFoundError(f"'{src_path}' does not exist")
    src_is_file = not stat["IsDir"]

    if sync:
        _refuse_unsafe_sync(dst_path, src_is_file)

    if not src_is_file and not recursive:
        error = f"'{src_path}' is a directory; use --recursive to copy it"
        print_error(error)
        record_transfer(src_path, dst_path, None, "failed", error=error)
        raise SystemExit(ExitCode.FAILURE)

    copy_remote(
        src_config=CONFIG_SRC,
        src_path=src_path,
        dst_config=CONFIG_DST,
        dst_path=dst_path,
        src_is_file=src_is_file,
        sync=sync,
        dry_run=ARGS_PARSER.dry_run or False,
    )

    print_info("Copy complete")


def _refuse_unsafe_sync(dst_path: str, src_is_file: bool) -> None:
    """
    Refuse a --sync, which deletes destination files not in the source,
    from a single file (there is no directory to mirror), or to a remote's
    root or the configured destination bucket itself, whose every other
    file it would delete.
    """
    problem = None
    path_part = dst_path.split(":", 1)[-1].strip("/")
    bucket = (CONFIG_DST.bucket or "").strip("/")
    if src_is_file:
        problem = "--sync mirrors a directory; copy a single file without it"
    elif path_part == "":
        problem = f"--sync to '{dst_path}' would delete from the remote's root itself"
    elif bucket and path_part == bucket:
        problem = (
            f"--sync to '{dst_path}' would delete from the bucket '{bucket}' itself"
        )
    if problem is not None:
        print_error(problem)
        print_error("Nothing was copied")
        raise SystemExit(ExitCode.USAGE)


if __name__ == "__main__":
    main()
