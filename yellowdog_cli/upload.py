#!/usr/bin/env python3

"""
Upload local files or directories to a remote data client.
"""

from pathlib import Path

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    resolve_remote_path,
    upload_directory,
    upload_file,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_error, print_info, print_warning
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone

CONFIG_DATA_CLIENT: ConfigDataClient = load_config_data_client()


@dataclient_wrapper
def main():
    if ARGS_PARSER.upgrade_rclone:
        upgrade_rclone()
        return

    if ARGS_PARSER.which_rclone:
        which_rclone()
        return

    sync = ARGS_PARSER.sync or False
    recursive = (ARGS_PARSER.recursive or False) or sync  # --sync implies --recursive
    flatten = ARGS_PARSER.flatten or False
    dry_run = ARGS_PARSER.dry_run or False
    destination = ARGS_PARSER.destination

    for local_path_str in ARGS_PARSER.local_paths:
        local_path = Path(local_path_str)

        if not local_path.exists():
            print_error(f"Path does not exist: '{local_path}'")
            continue

        if local_path.is_dir():
            if not recursive and not flatten:
                print_warning(
                    f"'{local_path}' is a directory; use --recursive or --flatten"
                    " to upload its contents"
                )
                continue
            remote_path = resolve_remote_path(
                CONFIG_DATA_CLIENT, relative_path=destination or local_path.name
            )
            upload_directory(
                CONFIG_DATA_CLIENT,
                local_path,
                remote_path,
                flatten=flatten,
                sync=sync,
                dry_run=dry_run,
            )
        else:
            if destination is None:
                remote_path = resolve_remote_path(
                    CONFIG_DATA_CLIENT, filename=local_path.name
                )
            elif destination.endswith("/") or len(ARGS_PARSER.local_paths) > 1:
                # The destination is a directory: retain each file's own name
                # (a single-object destination would make every uploaded file
                # overwrite the previous one)
                remote_path = resolve_remote_path(
                    CONFIG_DATA_CLIENT,
                    relative_path=f"{destination.rstrip('/')}/{local_path.name}",
                )
            else:
                remote_path = resolve_remote_path(
                    CONFIG_DATA_CLIENT, relative_path=destination
                )
            upload_file(CONFIG_DATA_CLIENT, local_path, remote_path, dry_run=dry_run)

    print_info("Upload complete")


if __name__ == "__main__":
    main()
