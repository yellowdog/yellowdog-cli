#!/usr/bin/env python3

"""
Delete files or directories from a remote data client.

Each path, or each item a wildcard matches, is listed once: what is shown
and confirmed is exactly what is deleted. The remote's root and a bare
bucket are refused before anything is deleted, a failure is recorded and
the rest still attempted, and a path already gone is skipped.
"""

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    delete_item,
    deletion_targets,
    describe_deletion,
    is_glob,
    record_deletion,
    resolve_remote_path,
    split_glob_remote_path,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.interactive import confirmed
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_dry_run, print_error, print_info
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

    # No paths, with --recursive (the command line refuses it without):
    # the entire default prefix. Each path given is deleted once
    remote_paths = [
        resolve_remote_path(CONFIG_DATA_CLIENT, relative_path=path)
        for path in dict.fromkeys(ARGS_PARSER.remote_paths or [])
    ] or [resolve_remote_path(CONFIG_DATA_CLIENT)]
    _refuse_roots(remote_paths)

    failed = 0
    for remote_path in remote_paths:
        try:
            failed += _delete(remote_path, recursive, dry_run)
        except Exception as e:
            # Not reachable: the path itself is what failed
            print_error(str(e))
            record_deletion(remote_path, False, "failed", error=str(e))
            failed += 1

    if failed:
        print_error(f"{failed} item(s) failed to delete")
        raise SystemExit(ExitCode.FAILURE)
    print_info("Deletion complete")


def _refuse_roots(remote_paths: list[str]) -> None:
    """
    Refuse, before anything is deleted, a path that is the remote's root or
    the configured bucket itself -- which with --no-prefix is what the
    'default prefix' is -- or a wildcard over the remote's root: deleting
    one would remove everything on the remote, or the bucket. A wildcard
    within the bucket deletes only what it matches there, and is allowed.
    """
    bucket = (CONFIG_DATA_CLIENT.bucket or "").strip("/")
    problems = []
    for remote_path in remote_paths:
        glob = is_glob(remote_path)
        # A wildcard deletes what it matches within its directory: refused
        # over the root, whose entries are the remote's buckets or top level
        path = split_glob_remote_path(remote_path)[0] if glob else remote_path
        path_part = path.split(":", 1)[-1].strip("/")
        if path_part == "" or (not glob and bucket and path_part == bucket):
            what = "the remote's root" if path_part == "" else f"the bucket '{bucket}'"
            problems.append(f"'{remote_path}' would delete from {what} itself")
    if problems:
        for problem in problems:
            print_error(problem)
        print_error(
            "Nothing was deleted: name a path within the bucket or prefix instead"
        )
        raise SystemExit(ExitCode.USAGE)


def _delete(remote_path: str, recursive: bool, dry_run: bool) -> int:
    """
    Delete one path, or what a wildcard matches, confirmed once; return how
    many items failed.
    """
    targets, failed = deletion_targets(CONFIG_DATA_CLIENT, remote_path, recursive)
    if not targets:
        return failed

    action = "Recursively delete" if recursive else "Delete"
    if dry_run:
        for path, is_dir in targets:
            print_dry_run(
                f"Would {action.lower()} "
                f"{describe_deletion(CONFIG_DATA_CLIENT, path, is_dir)}"
            )
            record_deletion(path, is_dir, "would delete")
        return failed

    if is_glob(remote_path):
        names = ", ".join(
            f"'{path.rsplit('/', 1)[-1]}{'/' if is_dir else ''}'"
            for path, is_dir in targets
        )
        print_info(f"Wildcard '{remote_path}' matches: {names}")
        question = f"{action} {len(targets)} matched item(s)?"
    else:
        question = f"{action} '{remote_path}'?"
    if not confirmed(question):
        for path, is_dir in targets:
            record_deletion(path, is_dir, "skipped")
        return failed

    for path, is_dir in targets:
        failed += 0 if delete_item(CONFIG_DATA_CLIENT, path, is_dir) else 1
    return failed


if __name__ == "__main__":
    main()
