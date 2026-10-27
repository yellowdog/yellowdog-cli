"""
Utility functions for rclone-backed data client commands:
yd-upload, yd-download, yd-delete, yd-ls.
"""

import fnmatch
import json
import os
import subprocess
import tempfile
import threading
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar, cast

from rclone_api import Config, Rclone
from rclone_api.completed_process import CompletedProcess as RcloneCompletedProcess
from rclone_api.dir_listing import DirListing

from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient.rclone import (
    make_rclone,
    make_rclone_for_copy,
    parse_rclone_config,
)
from yellowdog_cli.utils.glob_utils import GLOB_CHARS
from yellowdog_cli.utils.limits import (
    DATA_CLIENT_LISTING_WORKERS,
    DATA_CLIENT_NAMES_SHOWN,
    DATA_CLIENT_RCLONE_TRANSFERS,
    DATA_CLIENT_TRANSFER_WORKERS,
)
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_error,
    print_info,
    print_warning,
)
from yellowdog_cli.utils.results import json_requested, record
from yellowdog_cli.utils.variable_substitution import (
    literal_text,
    resolve_variables_in_string,
)

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


def remote_basename(remote_path: str) -> str:
    """
    The last segment of a resolved remote path ('remote:dir/name'): the
    remote's name is split off first, since a path at the remote's root
    ('loc:a.txt') has no '/' to split on, and a name may hold a ':'.
    """
    return remote_path.rstrip("/").split(":", 1)[-1].rsplit("/", 1)[-1]


def _rclone_error_detail(result) -> str:
    """
    Error detail for a failed rclone invocation: stderr is None when rclone
    ran uncaptured (output went to the terminal), so fall back to the code.
    """
    return result.stderr or f"rclone exit code {result.returncode}"


def join_remote(remote_dir: str, name: str) -> str:
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
    'rclone copy src dst' (dst is a directory to copy into), its files
    DATA_CLIENT_RCLONE_TRANSFERS at a time; see _copy_to().
    """
    return _without_rclone_api_warnings(
        lambda: rclone.copy(
            src=src, dst=dst, check=False, transfers=DATA_CLIENT_RCLONE_TRANSFERS
        )
    )


def listable(name: str) -> bool:
    """
    Whether a name can go in an rclone '--files-from-raw' list, which reads
    one name a line, exactly as written: any name but one holding a newline.
    """
    return "\n" not in name


def _with_names_file(names: list[str], call: Callable[[str], _T]) -> _T:
    """
    call(path) with the names written one a line (see listable()) to a
    private temporary file at 'path', removed afterwards.
    """
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", suffix=".txt", delete=False
    ) as listing:
        listing.write("".join(f"{name}\n" for name in names))
    try:
        return call(listing.name)
    finally:
        os.unlink(listing.name)


def _copy_files(
    rclone: Rclone, src_dir: str, dst_dir: str, names: list[str]
) -> RcloneCompletedProcess:
    """
    'rclone copy src_dir dst_dir' of the named files alone, each keeping its
    name, in one rclone process with rclone_api's parallel transfers, where
    one 'rclone copyto' per file costs a process start each, one after
    another (a tenth of a second or more apiece). The names are listed with
    '--files-from-raw', which, unlike '--files-from', reads a name beginning
    with '#' or ';', or with spaces, as it is.
    """
    return _with_names_file(
        names,
        lambda path: _without_rclone_api_warnings(
            lambda: rclone.copy(
                src=src_dir,
                dst=dst_dir,
                check=False,
                transfers=DATA_CLIENT_RCLONE_TRANSFERS,
                other_args=["--files-from-raw", path],
            )
        ),
    )


def _delete_files(
    rclone: Rclone, remote_dir: str, names: list[str]
) -> subprocess.CompletedProcess:
    """
    'rclone delete remote_dir' of the named files alone, in one rclone
    process (see _copy_files()).
    """
    return _with_names_file(
        names,
        lambda path: _run_quietly(
            rclone, ["delete", remote_dir, "--files-from-raw", path]
        ),
    )


def _copy_each(
    rclone: Rclone, pairs: list[tuple[str, str]]
) -> list[RcloneCompletedProcess]:
    """
    'rclone copyto source destination' for each pair, results in order,
    DATA_CLIENT_TRANSFER_WORKERS at a time: for files each renamed on the
    way (flattened), which one 'rclone copy' cannot do. Pairs sharing a
    destination (same-named files flattened together) are copied one after
    another, in order, so the later still wins.
    """
    by_destination: dict[str, list[int]] = {}
    for index, (_, destination) in enumerate(pairs):
        by_destination.setdefault(destination, []).append(index)

    def copy_in_turn(indexes: list[int]) -> list[tuple[int, RcloneCompletedProcess]]:
        return [(index, _copy_to(rclone, *pairs[index])) for index in indexes]

    def copy_all() -> list[RcloneCompletedProcess]:
        with ThreadPoolExecutor(
            max_workers=DATA_CLIENT_TRANSFER_WORKERS, initializer=_mark_quiet_worker
        ) as pool:
            done = [
                result
                for results in pool.map(copy_in_turn, by_destination.values())
                for result in results
            ]
        return [result for _, result in sorted(done, key=lambda item: item[0])]

    # As for the listing workers (see _files_of_matches())
    return _without_rclone_api_warnings(copy_all)


def _arrived(local_path: Path, size: int | None) -> bool:
    """
    Whether a downloaded file is in place at its expected size (any size,
    where the size is not known).
    """
    if not local_path.is_file():
        return False
    return size is None or size < 0 or local_path.stat().st_size == size


def _remote_sizes(rclone: Rclone, remote_dir: str) -> dict[str, int | None]:
    """
    The files directly in a remote directory, by name, with their sizes; none
    if it cannot be listed (it is then taken to hold none of them).
    """
    try:
        entries = _lsjson(rclone, remote_dir, files_only=True)
    except RuntimeError:
        return {}
    return {entry["Name"]: entry.get("Size") for entry in entries}


def summarise_names(names: list[str]) -> str:
    """
    Quoted names for a summary line: all of them, or the first
    DATA_CLIENT_NAMES_SHOWN and how many more, so that a wildcard matching
    100,000 files does not print 100,000 names.
    """
    shown = ", ".join(f"'{name}'" for name in names[:DATA_CLIENT_NAMES_SHOWN])
    more = len(names) - DATA_CLIENT_NAMES_SHOWN
    return shown if more <= 0 else f"{shown} and {more:,d} more"


def _lsjson(
    rclone: Rclone,
    remote_path: str,
    recursive: bool = False,
    files_only: bool = False,
    modtime: bool = False,
) -> list[dict]:
    """
    rclone's 'lsjson' entries for 'remote_path' (a directory's contents, or
    a file itself), raising if it cannot be listed. Without 'modtime' the
    entries have no 'ModTime': reading it costs a request per object on
    S3, which a directory of 100,000 objects does not finish in 30 minutes,
    so only a listing that shows it ('yd data list') asks for it.
    """
    args = ["lsjson", "--no-mimetype", *_modtime_args(modtime)]
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
    name = remote_basename(path) if path else path
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


def names_remote(config: ConfigDataClient, path: str) -> bool:
    """
    Whether a remote path argument is absolute, naming the configured
    remote ('loc:dir/a.txt'), rather than relative to the bucket and prefix.
    """
    remote_name, _ = parse_rclone_config(_require_remote(config))
    return path.startswith(f"{remote_name}:")


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
        relative_path = literal_text(
            cast(str, resolve_variables_in_string(relative_path))
        )
    if filename is not None:
        filename = literal_text(cast(str, resolve_variables_in_string(filename)))

    # Absolute rclone path — used as given, bar its '.' segments
    if relative_path is not None and names_remote(config, relative_path):
        path_part = relative_path[len(remote_name) + 1 :]
        return f"{remote_name}:{_without_current_directory_segments(path_part)}"

    parts = _configured_parts(config)
    if relative_path:
        relative_path = _without_current_directory_segments(relative_path)
        stripped = relative_path.strip("/")
        if stripped:
            # Preserve a trailing '/' — it denotes directory-destination intent
            # (e.g. for yd-copy / yd-upload)
            parts.append(stripped + ("/" if relative_path.endswith("/") else ""))
    elif filename:
        parts.append(filename)

    return f"{remote_name}:{_rooted(config)}{'/'.join(parts)}"


def _without_current_directory_segments(path: str) -> str:
    """
    'path' without its '.' segments, which name the directory they are in:
    the root, bucket and current-directory refusals compare paths as text,
    so 'bucket/.' would otherwise get past the one for 'bucket'. A leading
    '/' is kept, a trailing '.' is a trailing '/' ('a/.' names the
    directory 'a'), and '.' alone becomes ''.
    """
    segments = path.split("/")
    result = "/".join(segment for segment in segments if segment != ".")
    if path.startswith("/") and not result.startswith("/"):
        result = f"/{result}"
    if segments[-1] == "." and result and not result.endswith("/"):
        result += "/"
    return result


def sync_destination_problem(config: ConfigDataClient, remote_path: str) -> str | None:
    """
    Why a --sync to 'remote_path' would be refused, or None: it deletes
    every file there not in the source, so a remote's root or the configured
    bucket itself, whose every other file it would delete, is never a sync
    destination. Shared by yd-upload and yd-copy.
    """
    path_part = remote_path.split(":", 1)[-1].strip("/")
    bucket = (config.bucket or "").strip("/")
    if path_part == "":
        return f"--sync to '{remote_path}' would delete from the remote's root itself"
    if bucket and path_part == bucket:
        return (
            f"--sync to '{remote_path}' would delete from the bucket '{bucket}' itself"
        )
    return None


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


def _modtime_args(modtime: bool) -> list[str]:
    """
    The flag that keeps a listing from reading modification times, unless
    they are wanted (see _lsjson()).
    """
    return [] if modtime else ["--no-modtime"]


def _rclone_sync(rclone: Rclone, src: str, dst: str):
    """
    Run 'rclone sync src dst', making dst an exact mirror of src.
    rclone_api has no sync wrapper, so we call the underlying _run directly.
    Performance flags match _copy()'s, which are rclone_api's copy()'s with
    DATA_CLIENT_RCLONE_TRANSFERS. The
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
                str(DATA_CLIENT_RCLONE_TRANSFERS),
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
        rclone,
        ["lsjson", "-R", "--files-only", "--no-mimetype", "--no-modtime", remote_path],
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
            destination = join_remote(base, entry["Path"])
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
    return [
        (
            path,
            join_remote(remote_path, Path(path).relative_to(local_path).as_posix()),
            Path(path).stat().st_size,
        )
        for path in _local_files(local_path)
    ]


def flattened_destinations(local_path: Path, remote_path: str) -> list[str]:
    """
    Where a flattened upload of a local directory puts each of its files.
    """
    return [
        join_remote(remote_path, Path(path).name) for path in _local_files(local_path)
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

    destinations = [join_remote(remote_path, f.name) for f in files]
    if dry_run:
        return all(
            [
                upload_file(config, f, dest, dry_run=True)
                for f, dest in zip(files, destinations)
            ]
        )
    # Each file renamed to its own name directly under 'remote_path', which
    # one 'rclone copy' cannot do: copied several at once instead
    _, rclone = _rclone_for_config(config)
    print_info(
        f"Uploading (flat) {len(files):,d} file(s) '{local_path}' → '{remote_path}'"
    )
    results = _copy_each(
        rclone, [(str(f.resolve()), dest) for f, dest in zip(files, destinations)]
    )
    succeeded = True
    for local_file, dest, result in zip(files, destinations, results):
        size = local_file.stat().st_size
        if result.returncode != 0:
            error = f"Upload of '{local_file}' failed: {_rclone_error_detail(result)}"
            print_error(error)
            record_transfer(str(local_file), dest, size, "failed", error=error)
            succeeded = False
            continue
        record_transfer(str(local_file), dest, size, "uploaded")
    return succeeded


def upload_files(
    config: ConfigDataClient, uploads: list[tuple[Path, str]], dry_run: bool = False
) -> int:
    """
    Upload each (local file, remote path), recording each, and return how
    many failed. The files of one local directory going under their own
    names to one remote directory are uploaded in one rclone run
    (_copy_files()), and checked against a listing of the remote directory
    when it fails, since it may have uploaded some; any other file, as
    upload_file() uploads it. A symlink is one of those others: rclone,
    given its name in a list, skips it as a link it does not follow, or
    finds no such name in its target's directory, and reports neither.
    """
    if dry_run:
        return sum(
            0 if upload_file(config, local, remote, dry_run=True) else 1
            for local, remote in uploads
        )

    def directories(upload: tuple[Path, str]) -> tuple[Path, str] | None:
        local, remote = upload
        remote_dir, _, remote_name = remote.rpartition("/")
        if (
            remote_dir
            and remote_name == local.name
            and listable(local.name)
            and not local.is_symlink()
        ):
            return local.resolve().parent, remote_dir
        return None

    groups, singles = _by_directory(uploads, directories)
    failed = 0
    if groups:
        _, rclone = _rclone_for_config(config)
    for (local_dir, remote_dir), group in groups.items():
        files = [local for local, _ in group]
        print_info(
            f"Uploading {len(files):,d} file(s) from '{local_dir}' → '{remote_dir}'"
        )
        result = _copy_files(
            rclone, str(local_dir), remote_dir, [f.name for f in files]
        )
        present = {} if result.returncode == 0 else _remote_sizes(rclone, remote_dir)
        error = None
        for local in files:
            size = local.stat().st_size
            arrived = result.returncode == 0 or present.get(local.name) == size
            if not arrived and error is None:
                error = (
                    f"Upload from '{local_dir}' to '{remote_dir}' failed:"
                    f" {_rclone_error_detail(result)}"
                )
                print_error(error)
            record_transfer(
                str(local),
                f"{remote_dir}/{local.name}",
                size,
                "uploaded" if arrived else "failed",
                error=None if arrived else error,
            )
            failed += 0 if arrived else 1
    for local, remote in singles:
        failed += 0 if upload_file(config, local, remote) else 1
    return failed


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
    Format a one-line summary of the entries matched by a glob pattern, the
    first few named (summarise_names()). Directory names are suffixed with '/'.
    """
    names = [e["Name"] + ("/" if e["IsDir"] else "") for e in matches]
    return (
        f"Wildcard '{remote_path}' matches {len(names):,d} item(s):"
        f" {summarise_names(names)}"
    )


def remote_stat(
    rclone: Rclone, remote_path: str, confirm_directory: bool = True
) -> dict | None:
    """
    The lsjson entry of a remote path itself -- a file, or a directory,
    empty or not -- or None if it does not exist (rclone's exit code 3,
    'directory not found'). Any other failure to reach it raises, with
    rclone's own message, rather than reading as 'not there'.

    rclone answers a stat of a directory with an unnamed entry. A backend
    that can hold an empty directory (local, SFTP) answers a missing path
    with exit code 3, so there the entry is a directory; one that cannot (S3,
    Google Cloud Storage, Azure Blob: bucket-based storage has no
    directories) answers any path that is not an object with the same
    unnamed entry, exit 0, whether anything is stored under it or not, so
    there a directory exists only if a listing of it finds something, and an
    empty one is None, as it is to the storage itself. A listing passes
    'confirm_directory=False', for which such a path is the empty directory
    rclone says it is, and lists as one: an empty prefix, a namespace's
    before anything is uploaded to it among them, is no error to list.
    """
    stat_args = ["lsjson", "--stat", "--no-mimetype", remote_path]
    if confirm_directory:
        # A bucket-based stat of a directory lists it, as the listing that
        # confirms it holds anything does, so the two run at once: a
        # directory costs one listing's time rather than two, and a file or
        # a missing path no more than its stat, the listing of it as quick
        result, listing = _run_quietly_together(
            rclone, stat_args, _first_level_listing_args(remote_path)
        )
    else:
        result, listing = _run_quietly(rclone, stat_args), None
    if result.returncode == 3:
        return None
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot access '{remote_path}': {_rclone_error_detail(result)}"
        )
    entry = json.loads(result.stdout or "null")
    if (
        listing is not None
        and _is_unnamed_directory(entry)
        and not _can_hold_empty_directories(rclone, remote_path)
        and not _listing_holds_anything(listing, remote_path)
    ):
        return None
    return entry


def _is_unnamed_directory(entry: dict | None) -> bool:
    """
    Whether a stat answered with a directory entry that names nothing, as
    rclone answers for a directory, and a bucket-based remote for any path
    that is not an object.
    """
    return (
        entry is not None
        and bool(entry.get("IsDir"))
        and not entry.get("Name")
        and not entry.get("Path")
    )


def _can_hold_empty_directories(rclone: Rclone, remote_path: str) -> bool:
    """
    Whether the path's backend can hold an empty directory, as rclone's
    'backend features' reports it; one that cannot is bucket-based.
    """
    result = _run_quietly(rclone, ["backend", "features", remote_path])
    try:
        if result.returncode != 0:
            raise ValueError
        return bool(json.loads(result.stdout)["Features"]["CanHaveEmptyDirectories"])
    except (ValueError, KeyError, TypeError) as e:
        raise RuntimeError(
            f"Cannot tell what kind of storage '{remote_path}' is:"
            f" {_rclone_error_detail(result)}"
        ) from e


def _first_level_listing_args(remote_path: str) -> list[str]:
    """
    The listing of a directory's first level, without reading anything but
    the names (see _listing_holds_anything()).
    """
    return ["lsjson", "--no-mimetype", "--no-modtime", "--max-depth", "1", remote_path]


def _run_quietly_together(
    rclone: Rclone, first: list[str], second: list[str]
) -> tuple[subprocess.CompletedProcess, subprocess.CompletedProcess]:
    """
    _run_quietly() of two commands at the same time: the first on this
    thread, the second on a daemon thread, always waited for, so that the
    filter held here covers it (see _without_rclone_api_warnings()). A daemon
    thread rather than a pool's, whose threads the interpreter waits for as
    it exits: yd-doctor abandons a stat that outlasts its timeout, and the
    process must still end.
    """
    box: dict[str, Any] = {}

    def run_second() -> None:
        _mark_quiet_worker()
        try:
            box["result"] = _run_quietly(rclone, second)
        except BaseException as e:  # handed back to the caller
            box["error"] = e

    def run_both() -> tuple[subprocess.CompletedProcess, subprocess.CompletedProcess]:
        thread = threading.Thread(target=run_second, daemon=True)
        thread.start()
        try:
            result = _run_quietly(rclone, first)
        finally:
            thread.join()
        if "error" in box:
            raise box["error"]
        return result, box["result"]

    return _without_rclone_api_warnings(run_both)


def _listing_holds_anything(
    result: subprocess.CompletedProcess, remote_path: str
) -> bool:
    """
    Whether a listing of the directory's first level found anything in it.
    """
    if result.returncode == 3:
        return False
    if result.returncode != 0:
        raise RuntimeError(
            f"Cannot access '{remote_path}': {_rclone_error_detail(result)}"
        )
    return bool(json.loads(result.stdout or "[]"))


def glob_matches(
    rclone: Rclone, remote_path: str, allow_empty: bool = False, modtime: bool = False
) -> tuple[str, list[dict]]:
    """
    (parent directory, matching entries) for a wildcard remote path. An
    entry named exactly as the pattern is the one match: the wildcard
    characters are then part of a real name ('data[1].csv'), which as a
    pattern would match something else, or nothing. The parent not
    existing, or nothing matching, raises FileNotFoundError -- unless
    'allow_empty', for a listing, to which 'nothing matches' is an answer --
    and any other failure to list the parent raises with rclone's message.
    The entries have 'ModTime' only with 'modtime' (see _lsjson()).
    """
    remote_dir, pattern = split_glob_remote_path(remote_path)
    check = _run_quietly(
        rclone, ["lsjson", "--no-mimetype", *_modtime_args(modtime), remote_dir]
    )
    if check.returncode == 3:
        raise FileNotFoundError(f"'{remote_dir}' does not exist")
    if check.returncode != 0:
        raise RuntimeError(
            f"Cannot access '{remote_dir}': {_rclone_error_detail(check)}"
        )
    entries = json.loads(check.stdout or "[]")
    matches = [e for e in entries if e["Name"] == pattern] or [
        e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)
    ]
    if not matches and not allow_empty:
        raise FileNotFoundError(f"No matches for wildcard '{remote_path}'")
    return remote_dir, matches


def config_glob_matches(
    config: ConfigDataClient,
    remote_path: str,
    allow_empty: bool = False,
    modtime: bool = False,
) -> tuple[str, list[dict]]:
    """
    glob_matches() for a data client configuration.
    """
    _, rclone = _rclone_for_config(config)
    return glob_matches(rclone, remote_path, allow_empty, modtime)


def config_remote_stat(
    config: ConfigDataClient, remote_path: str, confirm_directory: bool = True
) -> dict | None:
    """
    remote_stat() for a data client configuration.
    """
    _, rclone = _rclone_for_config(config)
    return remote_stat(rclone, remote_path, confirm_directory)


def _download_with_glob(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    sync: bool = False,
    flatten: bool = False,
    flattened: dict[str, str] | None = None,
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
    flattened = {} if flattened is None else flattened
    succeeded = True
    # The matched files all go in one rclone run, each keeping its name
    batched = [e for e in matches if not e["IsDir"] and listable(e["Name"])]
    if batched:
        if flatten:
            for entry, files in zip(matches, files_of_matches):
                if not entry["IsDir"] and listable(entry["Name"]):
                    _warn_of_flattened_collisions(files, flattened)
        succeeded = _download_batch(rclone, remote_dir, batched, local_destination)
    for entry, files in zip(matches, files_of_matches):
        if not entry["IsDir"] and listable(entry["Name"]):
            continue
        src = join_remote(remote_dir, entry["Name"])
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


def _download_batch(
    rclone: Rclone, remote_dir: str, entries: list[dict], local_destination: Path
) -> bool:
    """
    Download the files of 'remote_dir' its lsjson entries name to
    'local_destination', each by its name, in one rclone run (_copy_files()),
    recording each. A run that fails may have fetched some of them, so each
    is recorded by whether it arrived at its size; False if any did not.
    """
    names = [entry["Name"] for entry in entries]
    print_info(
        f"Downloading {len(names):,d} matched file(s) from '{remote_dir}'"
        f" → '{local_destination}'"
    )
    result = _copy_files(rclone, remote_dir, str(local_destination), names)
    missing = (
        []
        if result.returncode == 0
        else [
            entry
            for entry in entries
            if not _arrived(local_destination / entry["Name"], entry.get("Size"))
        ]
    )
    error = None
    if missing:
        error = (
            f"Download of {len(missing):,d} file(s) from '{remote_dir}' failed:"
            f" {_rclone_error_detail(result)}"
        )
        print_error(error)
    missing_names = {entry["Name"] for entry in missing}
    for entry in entries:
        src = join_remote(remote_dir, entry["Name"])
        failed = entry["Name"] in missing_names
        record_transfer(
            src,
            str(local_destination / entry["Name"]),
            entry.get("Size"),
            "failed" if failed else "downloaded",
            error=error if failed else None,
            match=src.rstrip("/"),
        )
    return not missing


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
            join_remote(remote_path, f["Path"]),
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
    in hand and costs none. A single recursive listing of the parent is not
    used: Commander's pattern is '<tag>*' under the namespace directory,
    so it would list every tag's results to find this one's.
    """

    def files_of(entry: dict) -> list[tuple[str, str, int | None]]:
        src = join_remote(remote_dir, entry["Name"])
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
    'rclone copyto', several at once (_copy_each()), recording each in order;
    every file is tried, and False is returned if any failed.
    """
    succeeded = True
    results = _copy_each(rclone, [(source, dst) for source, dst, _ in files])
    for (source, destination, size), result in zip(files, results):
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
    flattened: dict[str, str] | None = None,
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
    'flattened' maps each local file a flattened download has already
    written to its source, for a caller downloading several remote paths
    into one destination to share, so that a file landing on one an earlier
    path fetched is warned of too.
    """
    flattened = {} if flattened is None else flattened
    if dry_run:
        _dry_run_download(
            config,
            remote_path,
            local_destination,
            flatten,
            sync,
            destination_is_item,
            flattened,
        )
        return True

    if is_glob(remote_path):
        return _download_with_glob(
            config,
            remote_path,
            local_destination,
            sync=sync,
            flatten=flatten,
            flattened=flattened,
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
        _warn_of_flattened_collisions(files, flattened)
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
    flattened: dict[str, str],
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
            for entry, files in zip(matches, files_of_matches):
                if flatten:
                    _warn_of_flattened_collisions(files, flattened)
                _record_downloads(
                    files, join_remote(remote_dir, entry["Name"]), "would download"
                )
        if sync:
            for entry in matches:
                if entry["IsDir"]:
                    _report_local_sync_deletions(
                        rclone,
                        join_remote(remote_dir, entry["Name"]),
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
            _warn_of_flattened_collisions(files, flattened)
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
        name = remote_basename(remote_path)
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
            (join_remote(remote_dir, entry["Name"]), bool(entry["IsDir"]))
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
    # 'rclone deletefile', not rclone_api's delete_files(), which lists the
    # file in a '--files-from' file: rclone reads a name there beginning with
    # '#' or ';' as a comment, trims leading spaces, and drops an absolute
    # path's leading '/', so the file would be left, or the deletion fail. Both
    # are run unchecked, so that a failure is recorded rather than raised
    if is_dir:
        print_info(f"Deleting directory '{path}'")
        result = _run_quietly(rclone, ["purge", path])
    else:
        print_info(f"Deleting '{path}'")
        result = _run_quietly(rclone, ["deletefile", path])
    if result.returncode != 0:
        error = f"Deletion of '{path}' failed: {_rclone_error_detail(result)}"
        print_error(error)
        record_deletion(path, is_dir, "failed", error=error)
        return False
    record_deletion(path, is_dir, "deleted")
    return True


def delete_items(config: ConfigDataClient, targets: list[tuple[str, bool]]) -> int:
    """
    Delete each (remote path, is a directory), recording each, and return
    how many failed. The files of one remote directory are deleted in one
    rclone run (_delete_files()), checked against a listing of the directory
    when it fails, since it may have deleted some; a directory, and a file
    alone in its directory, as delete_item() deletes it.
    """

    def directory(target: tuple[str, bool]) -> str | None:
        path, is_dir = target
        remote_dir, _, name = path.rstrip("/").rpartition("/")
        return remote_dir if not is_dir and remote_dir and listable(name) else None

    groups, singles = _by_directory(targets, directory)
    failed = 0
    if groups:
        _, rclone = _rclone_for_config(config)
    for remote_dir, group in groups.items():
        names = [path.rstrip("/").rpartition("/")[2] for path, _ in group]
        print_info(f"Deleting {len(names):,d} file(s) in '{remote_dir}'")
        result = _delete_files(rclone, remote_dir, names)
        left = (
            set() if result.returncode == 0 else _files_left(rclone, remote_dir, names)
        )
        error = None
        for name in names:
            path = f"{remote_dir}/{name}"
            if name in left:
                if error is None:
                    error = (
                        f"Deletion of files in '{remote_dir}' failed:"
                        f" {_rclone_error_detail(result)}"
                    )
                    print_error(error)
                record_deletion(path, False, "failed", error=error)
                failed += 1
            else:
                record_deletion(path, False, "deleted")
    for path, is_dir in singles:
        failed += 0 if delete_item(config, path, is_dir) else 1
    return failed


def _files_left(rclone: Rclone, remote_dir: str, names: list[str]) -> set[str]:
    """
    Which of the names are still in a remote directory after a failed
    deletion: all of them if it cannot be listed, as when the connection
    that failed the deletion is still lost, since none is known to have
    gone. (Not _remote_sizes(), which takes a directory it cannot list to
    hold none: safe for a transfer, whose files it fails, but not here.)
    """
    try:
        entries = _lsjson(rclone, remote_dir, files_only=True)
    except RuntimeError:
        return set(names)
    return {entry["Name"] for entry in entries}


_K = TypeVar("_K")


def _by_directory(
    items: list[_T], directory_of: Callable[[_T], _K | None]
) -> tuple[dict[_K, list[_T]], list[_T]]:
    """
    The items done in one rclone run each directory, the rest one at a time:
    grouped by what 'directory_of' gives an item (None for one done alone),
    a group of one done alone too. Returns the groups, and the rest in the
    order given.
    """
    keys = [directory_of(item) for item in items]
    counts: dict[_K, int] = {}
    for key in keys:
        if key is not None:
            counts[key] = counts.get(key, 0) + 1
    groups: dict[_K, list[_T]] = {}
    singles: list[_T] = []
    for item, key in zip(items, keys):
        if key is not None and counts[key] > 1:
            groups.setdefault(key, []).append(item)
        else:
            singles.append(item)
    return groups, singles


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
        if remote_stat(rclone, remote_path, confirm_directory=False) is None:
            raise FileNotFoundError(f"'{remote_path}' does not exist")
        entries = _lsjson(rclone, remote_path, recursive=recursive, modtime=True)
    else:
        remote_dir, matches = glob_matches(
            rclone, remote_path, allow_empty=True, modtime=True
        )
        entries = []
        for match in matches:
            entries.append(match)
            if recursive and match["IsDir"]:
                entries.extend(
                    {**entry, "Path": f"{match['Path']}/{entry['Path']}"}
                    for entry in _lsjson(
                        rclone,
                        join_remote(remote_dir, match["Name"]),
                        recursive=True,
                        modtime=True,
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
        dst_path + remote_basename(src_path) if dst_path.endswith("/") else dst_path
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
                    join_remote(src_path.rstrip("/"), f["Path"]),
                    join_remote(dst_path.rstrip("/"), f["Path"]),
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
        rclone,
        ["lsjson", "-R", "--files-only", "--no-mimetype", "--no-modtime", dst_path],
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
            _, destination = as_given(src_path, join_remote(base, entry["Path"]))
            print_dry_run(f"Would delete '{destination}'")
            record_transfer(None, destination, entry.get("Size"), "would delete")


def _renamed(path: str, name: str, new_name: str) -> str:
    """
    'path' with its remote prefix 'name:' replaced by 'new_name:'.
    """
    if name != new_name and path.startswith(f"{name}:"):
        return f"{new_name}:{path[len(name) + 1 :]}"
    return path
