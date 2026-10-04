#!/usr/bin/env python3

"""
Upload local files or directories to a remote data client.

Every argument's destination is worked out before anything is uploaded, so
that two arguments landing on the same remote path -- which would merge two
directories, or with --sync delete what the first uploaded -- are refused
before either is sent. Each argument is then uploaded in turn, a failure
recorded and the rest still attempted.
"""

from dataclasses import dataclass
from pathlib import Path

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    flattened_destinations,
    record_transfer,
    resolve_remote_path,
    upload_directory,
    upload_file,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone
from yellowdog_cli.utils.settings import ExitCode

CONFIG_DATA_CLIENT: ConfigDataClient = load_config_data_client()


@dataclass(frozen=True)
class _Upload:
    """
    One argument, and where it goes: a file to its own remote path, or a
    directory to the remote directory its contents are copied into.
    """

    argument: str
    local_path: Path
    remote_path: str
    is_dir: bool


@dataclient_wrapper
def main():
    if ARGS_PARSER.upgrade_rclone:
        upgrade_rclone()
        return

    if ARGS_PARSER.which_rclone:
        which_rclone()
        return

    sync = ARGS_PARSER.sync or False
    flatten = ARGS_PARSER.flatten or False
    dry_run = ARGS_PARSER.dry_run or False

    uploads, failed = _plan(ARGS_PARSER.local_paths, flatten, sync)
    _refuse_colliding_destinations(uploads, flatten)

    for upload in uploads:
        if upload.is_dir:
            succeeded = upload_directory(
                CONFIG_DATA_CLIENT,
                upload.local_path,
                upload.remote_path,
                flatten=flatten,
                sync=sync,
                dry_run=dry_run,
            )
        else:
            succeeded = upload_file(
                CONFIG_DATA_CLIENT, upload.local_path, upload.remote_path, dry_run
            )
        failed += 0 if succeeded else 1

    if failed:
        print_error(f"{failed} item(s) failed to upload")
        raise SystemExit(ExitCode.FAILURE)
    print_info("Upload complete")


def _plan(
    local_paths: list[str], flatten: bool, sync: bool
) -> tuple[list[_Upload], int]:
    """
    Each argument's upload, in the order given, and how many arguments
    failed already: a path that does not exist, or a directory given
    without --recursive, --flatten or --sync, each reported and recorded.
    """
    recursive = bool(ARGS_PARSER.recursive) or sync  # --sync implies --recursive
    destination = ARGS_PARSER.destination
    several = len(local_paths) > 1
    uploads: list[_Upload] = []
    failed = 0
    for local_path_str in local_paths:
        local_path = Path(local_path_str)

        if not local_path.exists():
            error = f"Path does not exist: '{local_path}'"
            print_error(error)
            # Neither sent anywhere nor, being missing, of any size
            record_transfer(local_path_str, None, None, "failed", error=error)
            failed += 1
            continue

        if local_path.is_dir() and not recursive and not flatten:
            error = (
                f"'{local_path}' is a directory; use --recursive or --flatten"
                " to upload its contents"
            )
            print_error(error)
            record_transfer(local_path_str, None, None, "failed", error=error)
            failed += 1
            continue

        if destination is None:
            # A directory's contents go to its own name, as a file does
            relative = local_path.name
        elif several or (destination.endswith("/") and not local_path.is_dir()):
            # The destination is a directory: each argument keeps its own
            # name in it, or every one would land on the same path
            relative = f"{destination.rstrip('/')}/{local_path.name}"
        else:
            relative = destination
        uploads.append(
            _Upload(
                local_path_str,
                local_path,
                resolve_remote_path(CONFIG_DATA_CLIENT, relative_path=relative),
                local_path.is_dir(),
            )
        )
    return uploads, failed


def _refuse_colliding_destinations(uploads: list[_Upload], flatten: bool) -> None:
    """
    Refuse, before anything is uploaded, two arguments whose uploads land on
    the same remote path: two directories would merge, and with --sync the
    second would delete what the first uploaded. A flattened directory's
    files are compared one by one, since that is where they land; files
    sharing a name within one flattened directory are warned of as the
    upload proceeds, as before.
    """
    owners: dict[str, str] = {}
    collisions: list[str] = []
    for upload in uploads:
        if upload.is_dir and flatten:
            destinations = set(
                flattened_destinations(upload.local_path, upload.remote_path)
            )
        else:
            destinations = {upload.remote_path.rstrip("/")}
        for destination in sorted(destinations):
            owner = owners.setdefault(destination, upload.argument)
            if owner != upload.argument:
                collisions.append(
                    f"'{owner}' and '{upload.argument}' would both be uploaded to"
                    f" '{destination}'"
                )
    if collisions:
        for collision in collisions:
            print_error(collision)
        print_error(
            "Nothing was uploaded: give the arguments separate destinations"
            " (separate runs with --destination)"
        )
        raise SystemExit(ExitCode.USAGE)


if __name__ == "__main__":
    main()
