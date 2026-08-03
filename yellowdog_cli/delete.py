#!/usr/bin/env python3

"""
Delete files or directories from a remote data client.
"""

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    delete_remote,
    entry_to_name,
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
    {"name", "path", "isDir"}, without deleting.

    'name' is the display basename, with a trailing '/' on a directory. 'path' is
    the resolved remote path and carries NO trailing slash even for a directory,
    because resolve_remote_path reads a trailing '/' as directory-destination
    intent (meaningful for yd-copy/yd-upload, wrong here). 'path' is the handle a
    caller passes back to delete that one item, so every entry must be joined to
    the parent directory IT came from — hence the rows are built inside the loop
    rather than over a flattened list of names.
    """
    rows: list[dict] = []
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
        # nothing yields no entries (rather than echoing the input). The parent it
        # returns already ends with '/', or is the bare remote prefix ('S3:') when
        # the path has no directory part.
        remote_dir, matches = list_remote_glob(CONFIG_DATA_CLIENT, remote_path)
        for entry in matches:
            rows.append(
                {
                    "name": entry_to_name(entry),
                    "path": f"{remote_dir}{entry['Name']}",
                    "isDir": bool(entry["IsDir"]),
                }
            )
    print_objects_as_json(rows)


if __name__ == "__main__":
    main()
