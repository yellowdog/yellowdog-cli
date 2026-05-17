#!/usr/bin/env python3

"""
Copy files or directories between remote data client locations.
"""

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import copy_remote, resolve_remote_path
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.load_config import (
    load_config_data_client,
    load_config_data_client_for_profile,
)
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone

CONFIG_SRC: ConfigDataClient = load_config_data_client()
CONFIG_DST: ConfigDataClient = load_config_data_client_for_profile(
    ARGS_PARSER.dst_profile,
    ARGS_PARSER.dst_prefix,
)


@dataclient_wrapper
def main():
    if ARGS_PARSER.upgrade_rclone:
        upgrade_rclone()
        return

    if ARGS_PARSER.which_rclone:
        which_rclone()
        return

    if ARGS_PARSER.src_path is None or ARGS_PARSER.dst_path is None:
        raise ValueError("Both <src-path> and <dst-path> are required")

    src_path = resolve_remote_path(CONFIG_SRC, relative_path=ARGS_PARSER.src_path)
    dst_path = resolve_remote_path(CONFIG_DST, relative_path=ARGS_PARSER.dst_path)

    sync = ARGS_PARSER.sync or False

    copy_remote(
        src_config=CONFIG_SRC,
        src_path=src_path,
        dst_config=CONFIG_DST,
        dst_path=dst_path,
        sync=sync,
        dry_run=ARGS_PARSER.dry_run or False,
    )

    print_info("Copy complete")


if __name__ == "__main__":
    main()
