"""
Utility functions for rclone-backed data client commands:
yd-upload, yd-download, yd-delete, yd-ls.
"""

import fnmatch
import json
import os
import subprocess
import threading
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar, cast

from rclone_api import Config, Rclone
from rclone_api.completed_process import CompletedProcess as RcloneCompletedProcess
from rclone_api.dir_listing import DirListing

from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.glob_utils import GLOB_CHARS
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.rclone_utils import (
    make_rclone,
    make_rclone_for_copy,
    parse_rclone_config,
)
from yellowdog_cli.utils.results import json_requested, record
from yellowdog_cli.utils.settings import DATA_CLIENT_LISTING_WORKERS
from yellowdog_cli.utils.variable_substitution import resolve_variables_in_string

# The keys of an rclone 'lsjson' entry that yd-ls records under '--json',
# spelled as rclone spells them; others vary by backend ('MimeType', 'IsBucket')
LSJSON_KEYS = ("Path", "Name", "Size", "ModTime", "IsDir")


def is_glob(path: str) -> bool:
    """
    Return True if path contains glob wildcard characters (*  ?  [).
    Only the path component after the remote: prefix is checked.
    """
    path_part = path.split(":", 1)[-1] if ":" in path else path
    return bool(GLOB_CHARS.intersection(path_part))


def _rclone_error_detail(result) -> str:
    """
    Error detail for a failed rclone invocation: stderr is None when rclone
    ran uncaptured (output went to the terminal), so fall back to the code.
    """
    return result.stderr or f"rclone exit code {result.returncode}"


def _join_remote(remote_dir: str, name: str) -> str:
    """
    A name within a remote directory: 'remote_dir' may end with '/', or be a
    bare 'remote:' (as glob_matches() returns it for a path with no
    directory part), which a '/' would turn into a different path.
    """
    if remote_dir.endswith(("/", ":")):
        return f"{remote_dir}{name}"
    return f"{remote_dir}/{name}"


_T = TypeVar("_T")


# Set in a listing worker thread, whose calls are silenced by the
# catch_warnings() its pool is run under (see _files_of_matches())
_IN_QUIET_WORKER = threading.local()


def _without_rclone_api_warnings(call: Callable[[], _T]) -> _T:
    """
    Make a listing call with rclone_api's UserWarning silenced: on a failed
    rclone run it warns with the whole command line (an inline remote's
    parameters included) and rclone's stderr, which reaches the user's stderr
    ahead of the command's own report of the same failure -- a missing path.
    Scoped to rclone_api's warnings, so any other still gets through.

    In a listing worker thread the call is made as it is: catch_warnings()
    saves and restores the process's filters, so entered and left by threads
    concurrently it would lift one thread's filter while another's call was
    still running, and leave a filter in place for good. The thread that runs
    the pool holds the filter for the pool's lifetime instead.
    """
    if getattr(_IN_QUIET_WORKER, "active", False):
        return call()
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore", category=UserWarning, module=r"rclone_api(\.|$)"
        )
        return call()


def _run_quietly(rclone: Rclone, args: list[str]) -> subprocess.CompletedProcess:
    """
    rclone.impl._run(args, capture=True), without rclone_api's warning on a
    non-zero exit: every caller checks the return code and reports it itself.
    """
    return _without_rclone_api_warnings(lambda: rclone.impl._run(args, capture=True))


def _copy_to(rclone: Rclone, src: str, dst: str) -> RcloneCompletedProcess:
    """
    'rclone copyto src dst' (dst is the file's own path), returning the result
    for the caller to check: rclone_api's default is check=True, which raises
    a CalledProcessError on a failed transfer before the caller can record it
    as 'failed', and its UserWarning is silenced as for a listing.
    """
    return _without_rclone_api_warnings(
        lambda: rclone.copy_to(src=src, dst=dst, check=False)
    )


def _copy(rclone: Rclone, src: str, dst: str) -> RcloneCompletedProcess:
    """
    'rclone copy src dst' (dst is a directory to copy into); see _copy_to().
    """
    return _without_rclone_api_warnings(
        lambda: rclone.copy(src=src, dst=dst, check=False)
    )


def _lsjson(
    rclone: Rclone,
    remote_path: str,
    recursive: bool = False,
    files_only: bool = False,
) -> list[dict]:
    """
    rclone's 'lsjson' entries for 'remote_path' (a directory's contents, or
    a file itself), raising if it cannot be listed.
    """
    args = ["lsjson", "--no-mimetype"]
    if recursive:
        args.append("-R")
    if files_only:
        args.append("--files-only")
    result = _run_quietly(rclone, [*args, remote_path])
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot list '{remote_path}': {_rclone_error_detail(result)}"
        )
    return json.loads(result.stdout or "[]")


def record_transfer(
    source: str | None,
    destination: str | None,
    size: int | None,
    action: str,
    error: str | None = None,
    **extra,
) -> None:
    """
    Record one file transferred by yd-upload, yd-download or yd-copy, as
    {"source", "destination", "size", "action"} (plus "error" when given, and
    any extra fields): 'action' is 'uploaded', 'downloaded' or 'copied',
    'skipped', 'failed', or 'would upload' (and so on) under '--dry-run'; a
    sync's dry run records each remote file it would remove as 'would
    delete', with no source.
    """
    item = {
        "source": source,
        "destination": destination,
        "size": size,
        "action": action,
    }
    if error is not None:
        item["error"] = error
    item.update(extra)
    record(item)


def record_deletion(
    remote_path: str, is_dir: bool, action: str, error: str | None = None
) -> None:
    """
    Record one item removed by yd-delete, as {"path", "action"} with its
    display "name" (a directory's with a trailing '/') and "isDir", which
    Commander offers its selection from; 'action' is 'deleted', 'failed',
    'skipped' (not there, or declined) or 'would delete'. The path carries no trailing '/', because it is the
    handle passed back to delete that one item.
    """
    path = remote_path.rstrip("/")
    name = path.rsplit("/", 1)[-1].split(":", 1)[-1] if path else path
    item = {
        "path": path,
        "action": action,
        "name": name + ("/" if is_dir else ""),
        "isDir": is_dir,
    }
    if error is not None:
        item["error"] = error
    record(item)


def _require_remote(config: ConfigDataClient) -> str:
    """
    Return config.remote, raising a clear error if it is not set.
    """
    if not config.remote:
        raise ValueError(
            "No rclone remote configured. "
            "Set 'remote' in the [dataClient] config section, "
            "via the YD_DATA_CLIENT_REMOTE environment variable, "
            "or with --remote."
        )
    return config.remote


def _rclone_for_config(config: ConfigDataClient):
    """
    Return (remote_name, Rclone) for the given data client config.
    """
    remote_str = _require_remote(config)
    remote_name, config_section = parse_rclone_config(remote_str)
    try:
        rclone = make_rclone(
            Config(config_section) if config_section is not None else None
        )
    except FileNotFoundError as e:
        raise FileNotFoundError(f"Remote '{remote_name}': {e}") from e
    return remote_name, rclone


def resolve_remote_path(
    config: ConfigDataClient,
    relative_path: str | None = None,
    filename: str | None = None,
) -> str:
    """
    Assemble a full rclone remote path from config plus an optional relative
    path or filename.

    If relative_path already starts with '<remote_name>:', it is returned
    verbatim (absolute rclone path).  Otherwise, the path is assembled as:
        <remote_name>:<bucket>/<prefix>/<relative_path_or_filename>
    keeping a leading '/' on the bucket (or, with no bucket, the prefix):
    on a local or SFTP remote that is an absolute path ('/data/results'),
    which without it would be taken relative to the current directory.
    Object-store bucket names never begin with one.
    """
    remote_str = _require_remote(config)
    remote_name, _ = parse_rclone_config(remote_str)

    # Each named, in an error or a warning, by the path itself, which is all
    # there is to name it by
    if relative_path is not None:
        relative_path = cast(str, resolve_variables_in_string(relative_path))
    if filename is not None:
        filename = cast(str, resolve_variables_in_string(filename))

    # Absolute rclone path — use verbatim
    if relative_path is not None and relative_path.startswith(f"{remote_name}:"):
        return relative_path

    parts = _configured_parts(config)
    if relative_path:
        stripped = relative_path.strip("/")
        if stripped:
            # Preserve a trailing '/' — it denotes directory-destination intent
            # (e.g. for yd-copy / yd-upload)
            parts.append(stripped + ("/" if relative_path.endswith("/") else ""))
    elif filename:
        parts.append(filename)

    return f"{remote_name}:{_rooted(config)}{'/'.join(parts)}"


def _configured_parts(config: ConfigDataClient, prefix: bool = True) -> list[str]:
    """
    The configured bucket and (unless not wanted) prefix, as path parts,
    without their slashes; _rooted() says whether the path is absolute.
    """
    parts = [
        part.strip("/")
        for part in (config.bucket, config.prefix if prefix else None)
        if part
    ]
    return [part for part in parts if part]


def _rooted(config: ConfigDataClient) -> str:
    """
    '/' when the configured path is absolute: the bucket, or with no bucket
    the prefix, begins with one (a local or SFTP remote's '/data/results').
    """
    first = config.bucket or config.prefix or ""
    return "/" if first.startswith("/") else ""


def resolve_bucket_path(config: ConfigDataClient) -> str:
    """
    The configured bucket's own path, '<remote_name>:<bucket>', a leading
    '/' kept as resolve_remote_path() keeps it.
    """
    remote_name, _ = parse_rclone_config(_require_remote(config))
    bucket_only = ConfigDataClient(remote=config.remote, bucket=config.bucket)
    return (
        f"{remote_name}:{_rooted(bucket_only)}"
        f"{'/'.join(_configured_parts(bucket_only, prefix=False))}"
    )


def upload_file(
    config: ConfigDataClient,
    local_path: Path,
    remote_path: str,
    dry_run: bool = False,
) -> bool:
    """
    Upload a single local file to the given remote path, recording the
    outcome. Returns False, having reported and recorded it, if it failed.
    """
    size = local_path.stat().st_size
    if dry_run:
        print_dry_run(f"Would upload '{local_path}' → '{remote_path}'")
        record_transfer(str(local_path), remote_path, size, "would upload")
        return True

    _, rclone = _rclone_for_config(config)
    print_info(f"Uploading '{local_path}' → '{remote_path}'")
    result = _copy_to(rclone, str(local_path.resolve()), remote_path)
    if result.returncode != 0:
        error = f"Upload of '{local_path}' failed: {_rclone_error_detail(result)}"
        print_error(error)
        record_transfer(str(local_path), remote_path, size, "failed", error=error)
        return False
    record_transfer(str(local_path), remote_path, size, "uploaded")
    return True


def _rclone_sync(rclone: Rclone, src: str, dst: str):
    """
    Run 'rclone sync src dst', making dst an exact mirror of src.
    rclone_api has no sync wrapper, so we call the underlying _run directly.
    Performance flags match those hardcoded in rclone_api's copy(). The
    result is returned for the caller to check, rclone_api's warning silenced
    as in _copy_to().
    """
    return _without_rclone_api_warnings(
        lambda: rclone.impl._run(
            [
                "sync",
                src,
                dst,
                "--checkers",
                "1000",
                "--transfers",
                "32",
                "--low-level-retries",
                "10",
            ],
            capture=False,
        )
    )


def upload_directory(
    config: ConfigDataClient,
    local_path: Path,
    remote_path: str,
    flatten: bool = False,
    sync: bool = False,
    dry_run: bool = False,
) -> bool:
    """
    Upload a local directory to the given remote path, recording the
    outcome. Returns False, having reported and recorded it, if anything
    failed.

    With flatten=True, all files are uploaded flat to the remote destination
    (no subdirectory structure preserved).
    With sync=True, the remote destination is made to mirror the local source
    (remote files not present locally are deleted).
    """
    if flatten:
        return _upload_directory_flat(config, local_path, remote_path, dry_run)

    # Walked only to be recorded, which nothing prints without '--json'
    files = _local_upload_files(local_path, remote_path) if json_requested() else []

    action = "sync" if sync else "copy"
    if dry_run:
        print_dry_run(f"Would {action} directory '{local_path}' → '{remote_path}'")
        for source, destination, size in files:
            record_transfer(source, destination, size, "would upload")
        if sync:
            _report_sync_deletions(config, local_path, remote_path)
        return True

    _, rclone = _rclone_for_config(config)
    print_info(f"{'Syncing' if sync else 'Uploading'} '{local_path}' → '{remote_path}'")
    if sync:
        result = _rclone_sync(rclone, src=str(local_path.resolve()), dst=remote_path)
    else:
        result = _copy(rclone, str(local_path.resolve()), remote_path)
    if result.returncode != 0:
        # One rclone run moved them all, so which of them failed is unknown
        error = (
            f"Upload of directory '{local_path}' failed: {_rclone_error_detail(result)}"
        )
        print_error(error)
        for source, destination, size in files:
            record_transfer(source, destination, size, "failed", error=error)
        if not files:  # Not walked: the directory itself is the record
            record_transfer(str(local_path), remote_path, None, "failed", error=error)
        return False
    for source, destination, size in files:
        record_transfer(source, destination, size, "uploaded")
    return True


def _report_sync_deletions(
    config: ConfigDataClient, local_path: Path, remote_path: str
) -> None:
    """
    In a dry run of a sync, report and record each remote file the sync
    would delete: those under the destination with no local counterpart.
    """
    _, rclone = _rclone_for_config(config)
    result = _run_quietly(
        rclone, ["lsjson", "-R", "--files-only", "--no-mimetype", remote_path]
    )
    if result.returncode == 3:  # rclone's 'directory not found': nothing there
        return
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot list '{remote_path}': {_rclone_error_detail(result)}"
        )
    local = {
        Path(source).relative_to(local_path).as_posix()
        for source in _local_files(local_path)
    }
    base = remote_path.rstrip("/")
    for entry in sorted(json.loads(result.stdout or "[]"), key=lambda e: e["Path"]):
        if entry["Path"] not in local:
            destination = _join_remote(base, entry["Path"])
            print_dry_run(f"Would delete '{destination}'")
            record_transfer(None, destination, entry.get("Size"), "would delete")


def _local_files(local_path: Path) -> list[str]:
    """
    The files under a local directory, sorted, as an upload sends them:
    rclone does not follow symlinks, so those are left out, with a warning.
    """
    files: list[str] = []
    symlinks = 0
    for directory, subdirectories, names in os.walk(local_path):
        symlinks += sum(
            1
            for name in subdirectories
            if os.path.islink(os.path.join(directory, name))
        )
        for name in names:
            path = os.path.join(directory, name)
            if os.path.islink(path):
                symlinks += 1
            else:
                files.append(path)
    if symlinks:
        print_warning(
            f"{symlinks} symbolic link(s) under '{local_path}' will not be uploaded"
        )
    return sorted(files)


def _local_upload_files(
    local_path: Path, remote_path: str
) -> list[tuple[str, str, int | None]]:
    """
    (source, destination, size) for each file in the local directory, as an
    rclone copy of it to 'remote_path' places it.
    """
    base = remote_path.rstrip("/")
    return [
        (
            path,
            f"{base}/{Path(path).relative_to(local_path).as_posix()}",
            Path(path).stat().st_size,
        )
        for path in _local_files(local_path)
    ]


def flattened_destinations(local_path: Path, remote_path: str) -> list[str]:
    """
    Where a flattened upload of a local directory puts each of its files.
    """
    return [
        f"{remote_path.rstrip('/')}/{Path(path).name}"
        for path in _local_files(local_path)
    ]


def _upload_directory_flat(
    config: ConfigDataClient,
    local_path: Path,
    remote_path: str,
    dry_run: bool,
) -> bool:
    """
    Upload all files under local_path to remote_path without preserving
    directory structure (all files land directly under remote_path). Every
    file is attempted; returns False if any failed.
    """
    files = [Path(path) for path in _local_files(local_path)]
    if not files:
        print_warning(f"No files found under '{local_path}'")
        record_transfer(str(local_path), remote_path, None, "skipped")
        return True

    # Flattening collapses subdirectories, so same-named files in different
    # subdirectories would silently overwrite each other at the remote
    seen: dict[str, Path] = {}
    for local_file in files:
        if (first := seen.get(local_file.name)) is not None:
            print_warning(
                f"'{local_file}' will overwrite '{first}' at the remote"
                f" (same filename, flattened upload)"
            )
        else:
            seen[local_file.name] = local_file

    succeeded = True
    for local_file in files:
        dest = f"{remote_path.rstrip('/')}/{local_file.name}"
        succeeded = upload_file(config, local_file, dest, dry_run=dry_run) and succeeded
    return succeeded


def entry_to_name(entry: dict) -> str:
    """
    One rclone lsjson entry's display name, with '/' appended to a directory.
    Factored out because this convention is needed per-entry (alongside that
    entry's path) as well as over a whole listing.
    """
    return entry["Name"] + ("/" if entry["IsDir"] else "")


def entries_to_names(entries: list[dict]) -> list[str]:
    """
    Map rclone lsjson entries to display names, appending '/' to directories.
    """
    return [entry_to_name(entry) for entry in entries]


def split_glob_remote_path(remote_path: str) -> tuple[str, str]:
    """
    Split a glob remote path into (parent_dir, pattern).

    'S3:bucket/prefix/xxx*' → ('S3:bucket/prefix/', 'xxx*')
    'S3:bucket/xxx*'        → ('S3:bucket/', 'xxx*')

    Wildcards are supported in the final path component only.
    """
    colon_idx = remote_path.find(":")
    remote_prefix = remote_path[: colon_idx + 1] if colon_idx >= 0 else ""
    path_part = remote_path[colon_idx + 1 :] if colon_idx >= 0 else remote_path

    if "/" in path_part:
        dir_part, pattern = path_part.rsplit("/", 1)
        if GLOB_CHARS.intersection(dir_part):
            raise ValueError(
                f"Wildcards are only supported in the final path component:"
                f" '{remote_path}'"
            )
        return f"{remote_prefix}{dir_part}/", pattern
    return f"{remote_prefix}", path_part


def _format_glob_matches(remote_path: str, matches: list[dict]) -> str:
    """
    Format a one-line summary of the entries matched by a glob pattern.
    Directory names are suffixed with '/'.
    """
    names = [f"'{e['Name'] + ('/' if e['IsDir'] else '')}'" for e in matches]
    return f"Wildcard '{remote_path}' matches: {', '.join(names)}"


def remote_stat(rclone: Rclone, remote_path: str) -> dict | None:
    """
    The lsjson entry of a remote path itself -- a file, or a directory,
    empty or not -- or None if it does not exist (rclone's exit code 3,
    'directory not found'). Any other failure to reach it raises, with
    rclone's own message, rather than reading as 'not there'.
    """
    result = _run_quietly(rclone, ["lsjson", "--stat", "--no-mimetype", remote_path])
    if result.returncode == 3:
        return None
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot access '{remote_path}': {_rclone_error_detail(result)}"
        )
    return json.loads(result.stdout or "null")


def glob_matches(
    rclone: Rclone, remote_path: str, allow_empty: bool = False
) -> tuple[str, list[dict]]:
    """
    (parent directory, matching entries) for a wildcard remote path. The
    parent not existing, or nothing matching, raises FileNotFoundError --
    unless 'allow_empty', for a listing, to which 'nothing matches' is an
    answer -- and any other failure to list the parent raises with rclone's
    message.
    """
    remote_dir, pattern = split_glob_remote_path(remote_path)
    check = _run_quietly(rclone, ["lsjson", "--no-mimetype", remote_dir])
    if check.returncode == 3:
        raise FileNotFoundError(f"'{remote_dir}' does not exist")
    if check.returncode != 0:
        raise RuntimeError(
            f"Cannot access '{remote_dir}': {_rclone_error_detail(check)}"
        )
    entries = json.loads(check.stdout or "[]")
    matches = [e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)]
    if not matches and not allow_empty:
        raise FileNotFoundError(f"No matches for wildcard '{remote_path}'")
    return remote_dir, matches


def config_glob_matches(
    config: ConfigDataClient, remote_path: str, allow_empty: bool = False
) -> tuple[str, list[dict]]:
    """
    glob_matches() for a data client configuration.
    """
    _, rclone = _rclone_for_config(config)
    return glob_matches(rclone, remote_path, allow_empty)


def config_remote_stat(config: ConfigDataClient, remote_path: str) -> dict | None:
    """
    remote_stat() for a data client configuration.
    """
    _, rclone = _rclone_for_config(config)
    return remote_stat(rclone, remote_path)


def _download_with_glob(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    sync: bool = False,
    flatten: bool = False,
) -> bool:
    """
    Download files whose names match a glob pattern. Returns False, having
    reported and recorded it, if any match failed; every match is tried.

    remote_path must contain wildcard characters in its final component, e.g.
    'S3:bucket/prefix/data_*.csv'.  Directory structure is preserved relative
    to the parent directory of the pattern, unless flatten=True, when every
    file of a matched directory is placed directly in local_destination.
    With sync=True, each matched directory is mirrored to its local copy,
    local files not present in the remote being deleted.
    """
    _, rclone = _rclone_for_config(config)
    remote_dir, matches = glob_matches(rclone, remote_path)
    print_info(_format_glob_matches(remote_path, matches))

    action = "Syncing" if sync else "Downloading"
    print_info(f"{action} '{remote_path}' → '{local_destination}'")
    local_destination.mkdir(parents=True, exist_ok=True)

    # Drive the transfer from the matched entries, so that the reported
    # matches and the transferred files always agree (rclone's '--include'
    # filter syntax differs subtly from the fnmatch syntax used above)
    # A flattened directory's files are listed to be transferred one by one;
    # otherwise they are listed only to be recorded, which only '--json' needs
    files_of_matches = (
        _files_of_matches(rclone, remote_dir, matches, local_destination, flatten)
        if json_requested() or flatten
        else [[] for _ in matches]
    )
    flattened: dict[str, str] = {}
    succeeded = True
    for entry, files in zip(matches, files_of_matches):
        src = _join_remote(remote_dir, entry["Name"])
        if flatten:
            _warn_of_flattened_collisions(files, flattened)
            if entry["IsDir"]:
                succeeded = _download_each(rclone, files, src) and succeeded
                continue
        dst = str(local_destination / entry["Name"])
        if entry["IsDir"]:
            result = _rclone_sync(rclone, src, dst) if sync else _copy(rclone, src, dst)
        else:
            result = _copy_to(rclone, src, dst)
        if result.returncode != 0:
            _download_failed(files, src, dst, _rclone_error_detail(result))
            succeeded = False
            continue
        _record_downloads(files, src, "downloaded")
    return succeeded


def _download_failed(
    files: list[tuple[str, str, int | None]], source: str, destination: str, detail: str
) -> None:
    """
    Report and record a transfer that failed: each of its files, or when
    they were not listed, the item itself.
    """
    error = f"Download of '{source}' failed: {detail}"
    print_error(error)
    if files:
        _record_downloads(files, source, "failed", error=error)
    else:
        record_transfer(
            source, destination, None, "failed", error=error, match=source.rstrip("/")
        )


def _download_files_of(
    rclone: Rclone,
    remote_path: str,
    is_dir: bool,
    local_path: Path,
    entry: dict | None = None,
    flatten: bool = False,
) -> list[tuple[str, str, int | None]]:
    """
    (source, destination, size) for each file a download of one remote item
    fetches: a file to 'local_path' itself, or each file in a directory to
    its place under 'local_path' -- or directly in it, flattened. 'entry' is
    the file's own lsjson entry, when the caller has it already.
    """
    if not is_dir:
        if entry is None:
            entries = _lsjson(rclone, remote_path)
            entry = entries[0] if entries else {}
        return [(remote_path, str(local_path), entry.get("Size"))]
    return [
        (
            _join_remote(remote_path, f["Path"]),
            str(local_path / (f["Name"] if flatten else f["Path"])),
            f.get("Size"),
        )
        for f in _lsjson(rclone, remote_path, recursive=True, files_only=True)
    ]


def _mark_quiet_worker() -> None:
    """
    A listing worker thread's initializer: see _without_rclone_api_warnings().
    """
    _IN_QUIET_WORKER.active = True


def _files_of_matches(
    rclone: Rclone,
    remote_dir: str,
    matches: list[dict],
    local_destination: Path,
    flatten: bool,
) -> list[list[tuple[str, str, int | None]]]:
    """
    For each entry a wildcard matched, in matched order, the files a download
    of it fetches (see _download_files_of()): a matched directory's under
    'local_destination' by its name -- or directly in it, flattened -- and a
    matched file's to 'local_destination/<name>'.

    Each directory costs one recursive listing, so they are listed
    concurrently, DATA_CLIENT_LISTING_WORKERS at a time; a file's entry is
    in hand and costs none. Listing the parent recursively once instead was
    rejected: Commander's pattern is '<tag>*' under the namespace directory,
    so it would list every tag's results to find this one's.
    """

    def files_of(entry: dict) -> list[tuple[str, str, int | None]]:
        src = _join_remote(remote_dir, entry["Name"])
        is_dir = bool(entry["IsDir"])
        flat = flatten and is_dir
        return _download_files_of(
            rclone,
            src,
            is_dir,
            local_destination if flat else local_destination / entry["Name"],
            entry,
            flatten=flat,
        )

    def list_all() -> list[list[tuple[str, str, int | None]]]:
        with ThreadPoolExecutor(
            max_workers=DATA_CLIENT_LISTING_WORKERS, initializer=_mark_quiet_worker
        ) as pool:
            return list(pool.map(files_of, matches))

    # The workers' listings are silenced by the filter held here, for as long
    # as the pool runs; its threads start inside it, so a context-aware
    # warnings module gives them the filter too
    return _without_rclone_api_warnings(list_all)


def _record_downloads(
    files: list[tuple[str, str, int | None]],
    match: str,
    action: str,
    error: str | None = None,
) -> None:
    """
    Record each file of one downloaded item. 'match' is the remote item the
    command's argument matched -- the file itself, or the directory it is in --
    which Commander offers its selection of top-level items from.
    """
    for source, destination, size in files:
        record_transfer(
            source, destination, size, action, error=error, match=match.rstrip("/")
        )


def _warn_of_flattened_collisions(
    files: list[tuple[str, str, int | None]], seen: dict[str, str]
) -> None:
    """
    Warn of each file a flattened download writes over another it fetches,
    'seen' mapping each destination already taken to its source: flattening
    collapses subdirectories, so same-named files in different ones land on
    one another, and the later wins.
    """
    for source, destination, _ in files:
        if (first := seen.get(destination)) is not None:
            print_warning(
                f"'{source}' will overwrite '{first}' locally"
                f" (same filename, flattened download)"
            )
        seen[destination] = source


def _download_each(
    rclone: Rclone, files: list[tuple[str, str, int | None]], match: str
) -> bool:
    """
    Download each (source, destination, size) to its own destination with
    'rclone copyto', recording each; every file is tried, and False is
    returned if any failed.
    """
    succeeded = True
    for source, destination, size in files:
        result = _copy_to(rclone, source, destination)
        if result.returncode != 0:
            error = f"Download of '{source}' failed: {_rclone_error_detail(result)}"
            print_error(error)
            _record_downloads([(source, destination, size)], match, "failed", error)
            succeeded = False
            continue
        _record_downloads([(source, destination, size)], match, "downloaded")
    return succeeded


def download_files(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    flatten: bool = False,
    sync: bool = False,
    dry_run: bool = False,
    destination_is_item: bool = False,
) -> bool:
    """
    Download from remote_path to local_destination. Returns False, having
    reported and recorded it, if a transfer failed; a remote path that does
    not exist, or a wildcard that matches nothing, raises FileNotFoundError,
    and a remote that cannot be reached raises, for the caller to record.

    remote_path may be a single file, a directory, or include glob patterns.
    With flatten=True, all remote files are placed directly in
    local_destination without preserving directory structure (never with
    sync, which the command line refuses). With sync=True, local files not
    present in the remote are deleted. With destination_is_item=True,
    local_destination is the remote item's own path rather than a directory
    to copy it into, so a single file is written to that path itself.
    """
    if dry_run:
        _dry_run_download(
            config, remote_path, local_destination, flatten, sync, destination_is_item
        )
        return True

    if is_glob(remote_path):
        return _download_with_glob(
            config, remote_path, local_destination, sync=sync, flatten=flatten
        )

    _, rclone = _rclone_for_config(config)
    stat = remote_stat(rclone, remote_path)
    if stat is None:
        raise FileNotFoundError(f"'{remote_path}' does not exist")
    is_file = not stat["IsDir"]
    dst = str(local_destination)

    if destination_is_item and is_file:
        # 'rclone copy' would treat the path as a directory to copy into
        files = [(remote_path, dst, stat.get("Size"))] if json_requested() else []
        print_info(f"Downloading '{remote_path}' → '{local_destination}'")
        result = _copy_to(rclone, remote_path, dst)
    elif flatten and not is_file:
        # Each file of the tree to its own name directly in the destination
        print_info(f"Downloading (flat) '{remote_path}' → '{local_destination}'")
        files = _download_files_of(
            rclone, remote_path, True, local_destination, flatten=True
        )
        _warn_of_flattened_collisions(files, {})
        local_destination.mkdir(parents=True, exist_ok=True)
        return _download_each(rclone, files, remote_path)
    else:
        files = (
            _literal_download_files(
                rclone,
                remote_path,
                local_destination,
                flatten,
                destination_is_item,
                stat,
            )
            if json_requested()
            else []
        )
        action = "Syncing" if sync and not is_file else "Downloading"
        print_info(f"{action} '{remote_path}' → '{local_destination}'")
        if sync and not is_file:
            result = _rclone_sync(rclone, src=remote_path, dst=dst)
        else:
            result = _copy(rclone, remote_path, dst)
    if result.returncode != 0:
        # One rclone run fetched them all, so which of them failed is unknown
        _download_failed(files, remote_path, dst, _rclone_error_detail(result))
        return False
    _record_downloads(files, remote_path, "downloaded")
    return True


def _dry_run_download(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    flatten: bool,
    sync: bool,
    destination_is_item: bool,
) -> None:
    """
    Report what download_files() would do, recording each file under
    '--json' (and listing them anyway to warn of flattened collisions);
    with sync, also each local file it would delete.
    """
    action = "sync" if sync else "download"
    _, rclone = _rclone_for_config(config)
    if is_glob(remote_path):
        remote_dir, matches = glob_matches(rclone, remote_path)
        names = [f"'{e['Name'] + ('/' if e['IsDir'] else '')}'" for e in matches]
        print_dry_run(
            f"Would {action} {len(matches)} matched item(s)"
            f" → '{local_destination}': {', '.join(names)}"
        )
        if json_requested() or flatten:
            files_of_matches = _files_of_matches(
                rclone, remote_dir, matches, local_destination, flatten
            )
            flattened: dict[str, str] = {}
            for entry, files in zip(matches, files_of_matches):
                if flatten:
                    _warn_of_flattened_collisions(files, flattened)
                _record_downloads(
                    files, _join_remote(remote_dir, entry["Name"]), "would download"
                )
        if sync:
            for entry in matches:
                if entry["IsDir"]:
                    _report_local_sync_deletions(
                        rclone,
                        _join_remote(remote_dir, entry["Name"]),
                        local_destination / entry["Name"],
                    )
        return

    stat = remote_stat(rclone, remote_path)
    if stat is None:
        raise FileNotFoundError(f"'{remote_path}' does not exist")
    if stat["IsDir"]:
        print_dry_run(
            f"Would {action} directory '{remote_path}' → '{local_destination}'"
        )
    else:
        print_dry_run(f"Would download '{remote_path}' → '{local_destination}'")
    if json_requested() or flatten:
        files = _literal_download_files(
            rclone, remote_path, local_destination, flatten, destination_is_item, stat
        )
        if flatten:
            _warn_of_flattened_collisions(files, {})
        _record_downloads(files, remote_path, "would download")
    if sync and stat["IsDir"]:
        _report_local_sync_deletions(rclone, remote_path, local_destination)


def _report_local_sync_deletions(
    rclone: Rclone, remote_path: str, local_path: Path
) -> None:
    """
    In a dry run of a download sync, report and record each local file the
    sync would delete: those under the local copy with no remote
    counterpart.
    """
    if not local_path.is_dir():
        return
    remote = {
        entry["Path"]
        for entry in _lsjson(rclone, remote_path, recursive=True, files_only=True)
    }
    for path in _local_files(local_path):
        relative = Path(path).relative_to(local_path).as_posix()
        if relative not in remote:
            print_dry_run(f"Would delete '{path}'")
            record_transfer(
                None, path, None, "would delete", match=remote_path.rstrip("/")
            )


def _literal_download_files(
    rclone: Rclone,
    remote_path: str,
    local_destination: Path,
    flatten: bool,
    destination_is_item: bool,
    stat: dict,
) -> list[tuple[str, str, int | None]]:
    """
    The files a download of a literal (not wildcard) remote path fetches:
    a file to the destination itself when that is the item's own path, and
    otherwise inside the destination directory, under its own name, as
    'rclone copy' puts it; a directory's contents in the destination.
    'stat' is the path's own lsjson entry.
    """
    if not stat["IsDir"]:
        if destination_is_item:
            return [(remote_path, str(local_destination), stat.get("Size"))]
        name = remote_path.rstrip("/").rsplit("/", 1)[-1]
        return [(remote_path, str(local_destination / name), stat.get("Size"))]
    return _download_files_of(
        rclone, remote_path, True, local_destination, flatten=flatten
    )


def deletion_targets(
    config: ConfigDataClient, remote_path: str, recursive: bool
) -> tuple[list[tuple[str, bool]], int]:
    """
    The (path, is_dir) items a deletion of 'remote_path' removes -- the path
    itself, or what a wildcard matches now, listed once so that what is
    confirmed is exactly what is deleted -- and how many items failed
    already: a directory without 'recursive' is reported and recorded as
    'failed', as 'rm' without '-r' fails. A path that does not exist, or a
    wildcard matching nothing, is reported and recorded as 'skipped' (gone
    already is what a deletion wants); a remote that cannot be reached
    raises, with rclone's message.
    """
    _, rclone = _rclone_for_config(config)
    if is_glob(remote_path):
        try:
            remote_dir, matches = glob_matches(rclone, remote_path)
        except FileNotFoundError as e:
            print_warning(str(e))
            record_deletion(remote_path, False, "skipped")
            return [], 0
        candidates = [
            (_join_remote(remote_dir, entry["Name"]), bool(entry["IsDir"]))
            for entry in matches
        ]
    else:
        stat = remote_stat(rclone, remote_path)
        if stat is None:
            print_warning(f"'{remote_path}' does not exist")
            record_deletion(remote_path, False, "skipped")
            return [], 0
        candidates = [(remote_path, bool(stat["IsDir"]))]

    targets: list[tuple[str, bool]] = []
    failed = 0
    for path, is_dir in candidates:
        if is_dir and not recursive:
            error = f"'{path}' is a directory; use --recursive to delete it"
            print_error(error)
            record_deletion(path, True, "failed", error=error)
            failed += 1
        else:
            targets.append((path, is_dir))
    return targets, failed


def describe_deletion(config: ConfigDataClient, path: str, is_dir: bool) -> str:
    """
    One item a deletion removes, as a dry run reports it: a directory with
    the number of files and subdirectories it holds.
    """
    if not is_dir:
        return f"'{path}'"
    _, rclone = _rclone_for_config(config)
    entries = _lsjson(rclone, path, recursive=True)
    n_dirs = sum(1 for entry in entries if entry["IsDir"])
    ies = "y" if n_dirs == 1 else "ies"
    return f"'{path}' ({len(entries) - n_dirs} file(s), {n_dirs} subdirector{ies})"


def delete_item(config: ConfigDataClient, path: str, is_dir: bool) -> bool:
    """
    Delete one remote file, or a directory tree, recording the outcome.
    Returns False, having reported and recorded it, if it failed.
    """
    _, rclone = _rclone_for_config(config)
    if is_dir:
        print_info(f"Deleting directory '{path}'")
        result = _without_rclone_api_warnings(lambda: rclone.purge(path))
    else:
        print_info(f"Deleting '{path}'")
        result = _without_rclone_api_warnings(lambda: rclone.delete_files(path))
    if result.returncode != 0:
        error = f"Deletion of '{path}' failed: {_rclone_error_detail(result)}"
        print_error(error)
        record_deletion(path, is_dir, "failed", error=error)
        return False
    record_deletion(path, is_dir, "deleted")
    return True


def lsjson_listing(
    config: ConfigDataClient, remote_path: str, recursive: bool = False
) -> list[dict]:
    """
    yd-ls's listing under '--json': rclone's 'lsjson' entries for
    'remote_path', each reduced to LSJSON_KEYS. A wildcard path gives the
    matching entries of its parent directory -- with a matching directory's
    contents too when recursive, their 'Path' relative to that parent, as
    rclone's own recursive listing of the parent would give it -- and none
    when nothing matches. A path that does not exist raises
    FileNotFoundError, and one that cannot be reached raises.
    """
    _, rclone = _rclone_for_config(config)
    if not is_glob(remote_path):
        if remote_stat(rclone, remote_path) is None:
            raise FileNotFoundError(f"'{remote_path}' does not exist")
        entries = _lsjson(rclone, remote_path, recursive=recursive)
    else:
        remote_dir, matches = glob_matches(rclone, remote_path, allow_empty=True)
        entries = []
        for match in matches:
            entries.append(match)
            if recursive and match["IsDir"]:
                entries.extend(
                    {**entry, "Path": f"{match['Path']}/{entry['Path']}"}
                    for entry in _lsjson(
                        rclone,
                        _join_remote(remote_dir, match["Name"]),
                        recursive=True,
                    )
                )
    return [{key: entry.get(key) for key in LSJSON_KEYS} for entry in entries]


def list_remote(
    config: ConfigDataClient,
    remote_path: str,
    recursive: bool = False,
) -> DirListing:
    """
    List files and directories at remote_path.

    Returns a DirListing with .files and .dirs attributes.
    With recursive=False, only the immediate contents are returned.
    """
    _, rclone = _rclone_for_config(config)
    max_depth = -1 if recursive else 1
    return _without_rclone_api_warnings(
        lambda: rclone.ls(src=remote_path, max_depth=max_depth)
    )


def copy_remote(
    src_config: ConfigDataClient,
    src_path: str,
    dst_config: ConfigDataClient,
    dst_path: str,
    src_is_file: bool,
    sync: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Copy from src_path to dst_path across (potentially different) remotes;
    the caller has established that the source exists and whether it is a
    file. With sync=True (a directory only), the destination is made to
    mirror the source, and a dry run reports each destination file it
    would delete. A single file is copied with 'rclone copyto', so the
    destination names the file itself (a rename), unless it ends with '/',
    when the file keeps its name inside it.
    """
    src_remote_str = _require_remote(src_config)
    dst_remote_str = _require_remote(dst_config)

    src_orig_name, _ = parse_rclone_config(src_remote_str)
    dst_orig_name, _ = parse_rclone_config(dst_remote_str)
    src_name, dst_name, rclone = make_rclone_for_copy(src_remote_str, dst_remote_str)

    # Colliding remote names are renamed by make_rclone_for_copy; the paths
    # were resolved with the original names, so rewrite their prefixes
    src_path = _renamed(src_path, src_orig_name, src_name)
    dst_path = _renamed(dst_path, dst_orig_name, dst_name)

    # Normalise shell tab-completion artefact: "dir/." → "dir/"
    if dst_path.endswith("/."):
        dst_path = dst_path[:-1]

    # Source is a single file: use copyto for precise destination naming.
    # If dst ends with '/', treat it as a directory and append the source filename.
    dst_file = (
        dst_path + src_path.rsplit("/", 1)[-1] if dst_path.endswith("/") else dst_path
    )

    def _as_given(source: str, destination: str) -> tuple[str, str]:
        # Named by the paths as the user gave them, rather than by the
        # collision-free names the transfer used
        return (
            _renamed(source, src_name, src_orig_name),
            _renamed(destination, dst_name, dst_orig_name),
        )

    # Each file copied, listed only to be recorded, which only '--json' needs
    files: list[tuple[str, str, int | None]] = []
    if json_requested():
        if src_is_file:
            entries = _lsjson(rclone, src_path)
            files = [(src_path, dst_file, entries[0].get("Size") if entries else None)]
        else:
            files = [
                (
                    _join_remote(src_path.rstrip("/"), f["Path"]),
                    _join_remote(dst_path.rstrip("/"), f["Path"]),
                    f.get("Size"),
                )
                for f in _lsjson(rclone, src_path, recursive=True, files_only=True)
            ]
        files = [(*_as_given(source, dest), size) for source, dest, size in files]

    if dry_run:
        action = "sync" if sync else "copy"
        print_dry_run(f"Would {action} '{src_path}' → '{dst_path}'")
        for source, destination, size in files:
            record_transfer(source, destination, size, "would copy")
        if sync:
            _report_copy_sync_deletions(rclone, src_path, dst_path, _as_given)
        return

    action = "Syncing" if sync else "Copying"
    print_info(f"{action} '{src_path}' → '{dst_path}'")

    if sync:
        result = _rclone_sync(rclone, src=src_path, dst=dst_path)
    elif src_is_file:
        result = _copy_to(rclone, src_path, dst_file)
    else:
        result = _copy(rclone, src_path, dst_path)

    if result.returncode != 0:
        # One rclone run copied them all, so which of them failed is unknown
        error = f"Copy failed: {_rclone_error_detail(result)}"
        for source, destination, size in files:
            record_transfer(source, destination, size, "failed", error=error)
        raise RuntimeError(error)
    for source, destination, size in files:
        record_transfer(source, destination, size, "copied")


def _report_copy_sync_deletions(
    rclone: Rclone,
    src_path: str,
    dst_path: str,
    as_given: Callable[[str, str], tuple[str, str]],
) -> None:
    """
    In a dry run of a copy sync, report and record each destination file
    the sync would delete: those with no counterpart in the source.
    """
    result = _run_quietly(
        rclone, ["lsjson", "-R", "--files-only", "--no-mimetype", dst_path]
    )
    if result.returncode == 3:  # rclone's 'directory not found': nothing there
        return
    if result.returncode != 0:
        raise RuntimeError(f"Cannot list '{dst_path}': {_rclone_error_detail(result)}")
    source = {
        entry["Path"]
        for entry in _lsjson(rclone, src_path, recursive=True, files_only=True)
    }
    base = dst_path.rstrip("/")
    for entry in sorted(json.loads(result.stdout or "[]"), key=lambda e: e["Path"]):
        if entry["Path"] not in source:
            _, destination = as_given(src_path, _join_remote(base, entry["Path"]))
            print_dry_run(f"Would delete '{destination}'")
            record_transfer(None, destination, entry.get("Size"), "would delete")


def _renamed(path: str, name: str, new_name: str) -> str:
    """
    'path' with its remote prefix 'name:' replaced by 'new_name:'.
    """
    if name != new_name and path.startswith(f"{name}:"):
        return f"{new_name}:{path[len(name) + 1 :]}"
    return path
