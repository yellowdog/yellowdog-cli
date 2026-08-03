#!/usr/bin/env python3

"""
Download files from a remote data client.
"""

from pathlib import Path

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    download_files,
    matched_item_rows,
    resolve_remote_path,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_info, print_objects_as_json
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone

CONFIG_DATA_CLIENT: ConfigDataClient = load_config_data_client()


def local_destination_for(
    remote_path_str: str,
    into_dir: str | None = None,
    explicit_destination: str | None = None,
) -> Path:
    """
    The local path a single remote item is downloaded to.

    The three modes answer different questions, which is why they are not
    interchangeable:

    - '--into <dir>' treats <dir> as a container: each item keeps its own name
      underneath it, so several items can be fetched without merging into one
      another. A *pattern* takes <dir> unchanged, because the glob transfer already
      places every match under the destination by its own name — otherwise the
      matches would land inside a directory literally named 'pyex*'.
    - '--destination <path>' names the local path *corresponding to* the remote
      item, so a directory's contents land directly in it. Unchanged behaviour.
    - With neither, a pattern expands into the current directory and a literal item
      mirrors its own name, so downloading 'mydir' creates './mydir/'.
    """
    is_pattern = any(c in remote_path_str for c in "*?[")
    basename = remote_path_str.rstrip("/").rsplit("/", 1)[-1]

    if into_dir:
        return Path(into_dir) if is_pattern else Path(into_dir) / basename
    if explicit_destination:
        return Path(explicit_destination)
    if is_pattern:
        return Path(".")
    return Path(basename)


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
    explicit_destination = ARGS_PARSER.destination
    into_dir = ARGS_PARSER.into

    if dry_run and ARGS_PARSER.json_output:
        # Enumeration only, in the same shape yd-delete emits: Commander uses it
        # to offer a selection of the matched top-level items. Nothing is
        # downloaded, and '--json' without '--dry-run' is rejected at parse time.
        print_objects_as_json(
            matched_item_rows(CONFIG_DATA_CLIENT, ARGS_PARSER.remote_paths)
        )
        return

    for remote_path_str in ARGS_PARSER.remote_paths:
        remote_path = resolve_remote_path(
            CONFIG_DATA_CLIENT, relative_path=remote_path_str
        )
        destination = local_destination_for(
            remote_path_str,
            into_dir=into_dir,
            explicit_destination=explicit_destination,
        )
        download_files(
            CONFIG_DATA_CLIENT,
            remote_path,
            destination,
            flatten=flatten,
            sync=sync,
            dry_run=dry_run,
        )

    print_info("Download complete")


if __name__ == "__main__":
    main()
