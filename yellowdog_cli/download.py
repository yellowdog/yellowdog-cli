#!/usr/bin/env python3

"""
Download files from a remote data client.
"""

from dataclasses import dataclass
from pathlib import Path

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    config_glob_matches,
    download_files,
    is_glob,
    record_transfer,
    resolve_remote_path,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.lazy import lazy
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_error, print_info
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone

CONFIG_DATA_CLIENT: ConfigDataClient = lazy(load_config_data_client)


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
    is_pattern = is_glob(remote_path_str)
    basename = remote_path_str.rstrip("/").rsplit("/", 1)[-1]

    if into_dir:
        return Path(into_dir) if is_pattern else Path(into_dir) / basename
    if explicit_destination:
        return Path(explicit_destination)
    if is_pattern:
        return Path(".")
    return Path(basename)


def destination_is_item(
    remote_path_str: str,
    into_dir: str | None = None,
    explicit_destination: str | None = None,
) -> bool:
    """
    Whether local_destination_for() gives the remote item its *own* path, as
    '--into' and the bare form do for a literal item, rather than naming a
    directory to copy it into, as '--destination' does. A single file is
    then transferred to that exact path: copied into it, as rclone copies
    into any destination, it would land inside a directory named after
    itself ('dli/a.txt/a.txt').
    """
    if is_glob(remote_path_str):
        return False
    return bool(into_dir) or not explicit_destination


@dataclass(frozen=True)
class _Download:
    """
    One remote path argument, resolved, and where it goes locally.
    """

    argument: str
    remote_path: str
    destination: Path
    destination_is_item: bool


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

    downloads = [
        _Download(
            remote_path_str,
            resolve_remote_path(CONFIG_DATA_CLIENT, relative_path=remote_path_str),
            local_destination_for(
                remote_path_str,
                into_dir=into_dir,
                explicit_destination=explicit_destination,
            ),
            destination_is_item(
                remote_path_str,
                into_dir=into_dir,
                explicit_destination=explicit_destination,
            ),
        )
        for remote_path_str in dict.fromkeys(ARGS_PARSER.remote_paths)
    ]
    if sync:
        _refuse_unsafe_syncs(downloads, explicit_destination)

    failed = 0
    for download in downloads:
        try:
            succeeded = download_files(
                CONFIG_DATA_CLIENT,
                download.remote_path,
                download.destination,
                flatten=flatten,
                sync=sync,
                dry_run=dry_run,
                destination_is_item=download.destination_is_item,
            )
        except Exception as e:
            # Not found, matching nothing, or not reachable: the argument
            # itself is what failed
            print_error(str(e))
            record_transfer(
                download.remote_path,
                str(download.destination),
                None,
                "failed",
                error=str(e),
                match=download.remote_path.rstrip("/"),
            )
            succeeded = False
        failed += 0 if succeeded else 1

    if failed:
        print_error(f"{failed} item(s) failed to download")
        raise SystemExit(ExitCode.FAILURE)
    print_info("Download complete")


def _refuse_unsafe_syncs(
    downloads: list[_Download], explicit_destination: str | None
) -> None:
    """
    Refuse, before anything is downloaded, a --sync that would delete what
    it should not: two arguments syncing into one local path, where the
    second would delete what the first downloaded; or a sync into the
    current directory itself (a remote path naming the prefix, '/'), which
    would delete every local file not in the remote, unless the current
    directory was named explicitly with '-d .'. A wildcard's matches are
    listed for this, since each is synced to a path of its own.
    """
    owners: dict[Path, str] = {}
    problems: list[str] = []
    cwd = Path.cwd().resolve()
    for download in downloads:
        if is_glob(download.remote_path):
            try:
                _, matches = config_glob_matches(
                    CONFIG_DATA_CLIENT, download.remote_path
                )
            except Exception:
                continue  # Reported as that argument's failure when it is tried
            targets = [download.destination / entry["Name"] for entry in matches]
        else:
            targets = [download.destination]
        for target in targets:
            resolved = target.resolve()
            if resolved == cwd and explicit_destination is None:
                problems.append(
                    f"'{download.argument}' would be synced into the current"
                    " directory, deleting every file in it that is not in the"
                    " remote; name it with '-d .' if that is what is meant"
                )
                continue
            owner = owners.setdefault(resolved, download.argument)
            if owner != download.argument:
                problems.append(
                    f"'{owner}' and '{download.argument}' would both be synced to"
                    f" '{target}', the second deleting what the first downloaded"
                )
    if problems:
        for problem in problems:
            print_error(problem)
        print_error("Nothing was downloaded")
        raise SystemExit(ExitCode.USAGE)


if __name__ == "__main__":
    main()
