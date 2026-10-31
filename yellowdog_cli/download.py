#!/usr/bin/env python3

"""
Download files from a remote data client.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.context import DataClientContext
from yellowdog_cli.utils.dataclient.operations import (
    config_glob_matches,
    download_files,
    is_glob,
    names_remote,
    record_transfer,
    remote_basename,
    resolve_remote_path,
)
from yellowdog_cli.utils.dataclient.rclone import upgrade_rclone, which_rclone
from yellowdog_cli.utils.dataclient.wrapper import dataclient_wrapper
from yellowdog_cli.utils.exit_codes import ExitCode
from yellowdog_cli.utils.lazy import lazy
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import counted, print_error, print_info
from yellowdog_cli.utils.settings import WINDOWS_RESERVED_CHARACTERS

CONFIG_DATA_CLIENT: ConfigDataClient = lazy(load_config_data_client)


def local_destination_for(
    remote_path_str: str,
    into_dir: str | None = None,
    explicit_destination: str | None = None,
    names_remote: bool = False,
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

    'names_remote' says the path begins with the remote's name, which is
    split off: at the remote's root ('loc:a.txt') there is no '/' to split
    on. A relative path's ':' is its own, and one naming the prefix itself
    ('/') has no name, so is the current directory.
    """
    is_pattern = is_glob(remote_path_str)
    basename = (
        remote_basename(remote_path_str)
        if names_remote
        else remote_path_str.rstrip("/").rsplit("/", 1)[-1]
    )

    if explicit_destination:
        return Path(explicit_destination)
    if is_pattern:
        return Path(into_dir) if into_dir else Path(".")
    _check_local_name(basename)
    return Path(into_dir) / basename if into_dir else Path(basename)


def _check_local_name(name: str) -> None:
    """
    Refuse, on Windows, a remote item's own name that no Windows file name
    may hold; '--destination' names the local path instead. The files inside
    a directory downloaded are rclone's to name, which it does.
    """
    if sys.platform != "win32":
        return
    reserved = sorted({c for c in name if c in WINDOWS_RESERVED_CHARACTERS})
    if reserved:
        raise ValueError(
            f"'{name}' cannot be a file name on Windows, which does not allow"
            f" {', '.join(repr(c) for c in reserved)} in one; give"
            " '--destination' to name the local file"
        )


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
def main(ctx: DataClientContext):
    if ctx.args.upgrade_rclone:
        upgrade_rclone()
        return

    if ctx.args.which_rclone:
        which_rclone()
        return

    sync = ctx.args.sync or False
    flatten = ctx.args.flatten or False
    dry_run = ctx.args.dry_run or False
    explicit_destination = ctx.args.destination
    into_dir = ctx.args.into

    failed = 0
    downloads: list[_Download] = []
    for remote_path_str in dict.fromkeys(ctx.args.remote_paths):
        remote_path = resolve_remote_path(
            CONFIG_DATA_CLIENT, relative_path=remote_path_str
        )
        try:
            destination = local_destination_for(
                remote_path_str,
                into_dir=into_dir,
                explicit_destination=explicit_destination,
                names_remote=names_remote(CONFIG_DATA_CLIENT, remote_path_str),
            )
        except ValueError as e:
            # A name no local file can have: that item alone fails
            print_error(str(e))
            record_transfer(
                remote_path,
                "",
                None,
                "failed",
                error=str(e),
                match=remote_path.rstrip("/"),
            )
            failed += 1
            continue
        downloads.append(
            _Download(
                remote_path_str,
                remote_path,
                destination,
                destination_is_item(
                    remote_path_str,
                    into_dir=into_dir,
                    explicit_destination=explicit_destination,
                ),
            )
        )
    unchecked = _refuse_unsafe_syncs(downloads, explicit_destination) if sync else {}

    # Shared by every argument, so that a flattened file landing on one an
    # earlier argument fetched is warned of, as one within an argument is
    flattened: dict[str, str] = {}
    for download in downloads:
        if (error := unchecked.get(download.argument)) is not None:
            # Never synced unchecked: its listing could succeed the second time
            message = (
                f"'{download.argument}' could not be checked for a safe --sync,"
                f" so was not synced: {error}"
            )
            print_error(message)
            record_transfer(
                download.remote_path,
                str(download.destination),
                None,
                "failed",
                error=message,
                match=download.remote_path.rstrip("/"),
            )
            failed += 1
            continue
        try:
            succeeded = download_files(
                CONFIG_DATA_CLIENT,
                download.remote_path,
                download.destination,
                flatten=flatten,
                sync=sync,
                dry_run=dry_run,
                destination_is_item=download.destination_is_item,
                flattened=flattened,
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
        print_error(f"{counted(failed, 'item')} failed to download")
        raise SystemExit(ExitCode.FAILURE)
    print_info(
        "Dry run complete: nothing was downloaded" if dry_run else "Download complete"
    )


def _refuse_unsafe_syncs(
    downloads: list[_Download], explicit_destination: str | None
) -> dict[str, Exception]:
    """
    Refuse, before anything is downloaded, a --sync that would delete what
    it should not: two arguments syncing into one local path, where the
    second would delete what the first downloaded; or a sync into the
    current directory itself (a remote path naming the prefix, '/'), which
    would delete every local file not in the remote, unless the current
    directory was named explicitly with '-d .'. A wildcard's matches are
    listed for this, since each is synced to a path of its own. Returns the
    wildcards whose listing failed, other than by matching nothing, and why,
    for the caller to fail rather than sync unchecked.
    """
    owners: dict[Path, str] = {}
    problems: list[str] = []
    unchecked: dict[str, Exception] = {}
    cwd = Path.cwd().resolve()
    for download in downloads:
        if is_glob(download.remote_path):
            try:
                _, matches = config_glob_matches(
                    CONFIG_DATA_CLIENT, download.remote_path
                )
            except FileNotFoundError:
                # Nothing matches, so nothing to overlap: the argument fails
                # as matching nothing when it is tried
                continue
            except Exception as e:
                unchecked[download.argument] = e
                continue
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
    return unchecked


if __name__ == "__main__":
    main()
