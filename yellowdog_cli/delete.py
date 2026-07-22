#!/usr/bin/env python3

"""
Delete files or directories from a remote data client.
"""

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    delete_remote,
    entries_to_names,
    is_glob,
    list_remote_glob,
    resolve_remote_path,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_info, print_objects_as_json
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

    recursive = ARGS_PARSER.recursive or False
    dry_run = ARGS_PARSER.dry_run or False
    remote_paths = ARGS_PARSER.remote_paths or []

    if dry_run and ARGS_PARSER.json_output:
        _emit_matched_json(remote_paths)
        return

    if not remote_paths:
        # No paths supplied: operate on the entire default prefix
        remote_path = resolve_remote_path(CONFIG_DATA_CLIENT)
        if not recursive:
            print_info(
                "No remote paths specified. "
                f"Use --recursive to delete the entire prefix: '{remote_path}'"
            )
            return
        _delete_one(remote_path, recursive=True, dry_run=dry_run)
    else:
        for path_str in remote_paths:
            remote_path = resolve_remote_path(
                CONFIG_DATA_CLIENT, relative_path=path_str
            )
            _delete_one(remote_path, recursive=recursive, dry_run=dry_run)

    print_info("Deletion complete")


def _delete_one(remote_path: str, recursive: bool, dry_run: bool) -> None:
    if dry_run:
        delete_remote(
            CONFIG_DATA_CLIENT, remote_path, recursive=recursive, dry_run=True
        )
        return

    if is_glob(remote_path):
        _, matches = list_remote_glob(CONFIG_DATA_CLIENT, remote_path)
        if not matches:
            print_info(f"No matches for wildcard '{remote_path}'")
            return
        names = [f"'{e['Name'] + ('/' if e['IsDir'] else '')}'" for e in matches]
        print_info(f"Wildcard '{remote_path}' matches: {', '.join(names)}")
        action = "Recursively delete" if recursive else "Delete"
        if confirmed(f"{action} {len(matches)} matched item(s)?"):
            delete_remote(CONFIG_DATA_CLIENT, remote_path, recursive=recursive)
        return

    action = "Recursively delete" if recursive else "Delete"
    if confirmed(f"{action} '{remote_path}'?"):
        delete_remote(CONFIG_DATA_CLIENT, remote_path, recursive=recursive)


def _emit_matched_json(remote_paths: list[str]) -> None:
    """
    Print the top-level items a delete would match, as a JSON array of
    {"name": ...} (directories carry a trailing '/'), without deleting.
    """
    names: list[str] = []
    resolved = (
        [resolve_remote_path(CONFIG_DATA_CLIENT)]
        if not remote_paths
        else [
            resolve_remote_path(CONFIG_DATA_CLIENT, relative_path=p)
            for p in remote_paths
        ]
    )
    for remote_path in resolved:
        # list_remote_glob handles a literal (non-glob) final component too: it
        # lists the parent and exact-matches the name, so a path that matches
        # nothing yields no entries (rather than echoing the input). This gives
        # consistent basenames (with '/' on dirs) and reflects what a real
        # delete would actually remove.
        _, matches = list_remote_glob(CONFIG_DATA_CLIENT, remote_path)
        names.extend(entries_to_names(matches))
    print_objects_as_json([{"name": name} for name in names])


if __name__ == "__main__":
    main()
