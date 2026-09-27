"""
Utility functions for rclone-backed data client commands:
yd-upload, yd-download, yd-delete, yd-ls.
"""

import fnmatch
import json
import subprocess
import threading
import warnings
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TypeVar, cast

from rclone_api import Config, Rclone
from rclone_api.dir_listing import DirListing

from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.glob_utils import GLOB_CHARS
from yellowdog_cli.utils.printing import print_dry_run, print_info, print_warning
from yellowdog_cli.utils.rclone_utils import (
    make_rclone,
    make_rclone_for_copy,
    parse_rclone_config,
)
from yellowdog_cli.utils.results import json_requested, record
from yellowdog_cli.utils.settings import DATA_CLIENT_LISTING_WORKERS
from yellowdog_cli.utils.variables import resolve_variables_in_string

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
    bare 'remote:' (as list_remote_glob() returns it for a path with no
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
    source: str,
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
    'skipped', 'failed', or 'would upload' (and so on) under '--dry-run'.
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


def _record_deletion(
    remote_path: str, is_dir: bool, action: str, error: str | None = None
) -> None:
    """
    Record one item removed by yd-delete, as {"path", "action"} with its
    display "name" (a directory's with a trailing '/') and "isDir", which
    Commander offers its selection from; 'action' is 'deleted', 'failed' or
    'would delete'. The path carries no trailing '/', because it is the
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

    parts: list[str] = []
    if config.bucket:
        parts.append(config.bucket.strip("/"))
    if config.prefix:
        parts.append(config.prefix.strip("/"))
    if relative_path:
        stripped = relative_path.strip("/")
        if stripped:
            # Preserve a trailing '/' — it denotes directory-destination intent
            # (e.g. for yd-copy / yd-upload)
            parts.append(stripped + ("/" if relative_path.endswith("/") else ""))
    elif filename:
        parts.append(filename)

    return f"{remote_name}:{'/'.join(parts)}"


def upload_file(
    config: ConfigDataClient,
    local_path: Path,
    remote_path: str,
    dry_run: bool = False,
) -> None:
    """
    Upload a single local file to the given remote path.
    """
    size = local_path.stat().st_size
    if dry_run:
        print_dry_run(f"Would upload '{local_path}' → '{remote_path}'")
        record_transfer(str(local_path), remote_path, size, "would upload")
        return

    _, rclone = _rclone_for_config(config)
    print_info(f"Uploading '{local_path}' → '{remote_path}'")
    result = rclone.copy_to(src=str(local_path.resolve()), dst=remote_path)
    if result.returncode != 0:
        error = f"Upload failed: {_rclone_error_detail(result)}"
        record_transfer(str(local_path), remote_path, size, "failed", error=error)
        raise RuntimeError(error)
    record_transfer(str(local_path), remote_path, size, "uploaded")


def _rclone_sync(rclone: Rclone, src: str, dst: str):
    """
    Run 'rclone sync src dst', making dst an exact mirror of src.
    rclone_api has no sync wrapper, so we call the underlying _run directly.
    Performance flags match those hardcoded in rclone_api's copy().
    """
    return rclone.impl._run(
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


def upload_directory(
    config: ConfigDataClient,
    local_path: Path,
    remote_path: str,
    flatten: bool = False,
    sync: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Upload a local directory to the given remote path.

    With flatten=True, all files are uploaded flat to the remote destination
    (no subdirectory structure preserved).
    With sync=True, the remote destination is made to mirror the local source
    (remote files not present locally are deleted).
    """
    if flatten:
        _upload_directory_flat(config, local_path, remote_path, dry_run)
        return

    # Walked only to be recorded, which nothing prints without '--json'
    files = _local_upload_files(local_path, remote_path) if json_requested() else []

    action = "sync" if sync else "copy"
    if dry_run:
        print_dry_run(f"Would {action} directory '{local_path}' → '{remote_path}'")
        for source, destination, size in files:
            record_transfer(source, destination, size, "would upload")
        return

    _, rclone = _rclone_for_config(config)
    print_info(f"{'Syncing' if sync else 'Uploading'} '{local_path}' → '{remote_path}'")
    if sync:
        result = _rclone_sync(rclone, src=str(local_path.resolve()), dst=remote_path)
    else:
        result = rclone.copy(src=str(local_path.resolve()), dst=remote_path)
    if result.returncode != 0:
        # One rclone run moved them all, so which of them failed is unknown
        error = f"Directory upload failed: {_rclone_error_detail(result)}"
        for source, destination, size in files:
            record_transfer(source, destination, size, "failed", error=error)
        raise RuntimeError(error)
    for source, destination, size in files:
        record_transfer(source, destination, size, "uploaded")


def _local_upload_files(
    local_path: Path, remote_path: str
) -> list[tuple[str, str, int | None]]:
    """
    (source, destination, size) for each file in the local directory, as an
    rclone copy of it to 'remote_path' places it.
    """
    base = remote_path.rstrip("/")
    return [
        (str(f), f"{base}/{f.relative_to(local_path).as_posix()}", f.stat().st_size)
        for f in sorted(local_path.rglob("*"))
        if f.is_file()
    ]


def _upload_directory_flat(
    config: ConfigDataClient,
    local_path: Path,
    remote_path: str,
    dry_run: bool,
) -> None:
    """
    Upload all files under local_path to remote_path without preserving
    directory structure (all files land directly under remote_path).
    """
    files = [f for f in local_path.rglob("*") if f.is_file()]
    if not files:
        print_info(f"No files found under '{local_path}'")
        return

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

    for local_file in files:
        dest = f"{remote_path.rstrip('/')}/{local_file.name}"
        upload_file(config, local_file, dest, dry_run=dry_run)


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


def _split_glob_remote_path(remote_path: str) -> tuple[str, str]:
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


def _download_with_glob(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    sync: bool = False,
    flatten: bool = False,
) -> None:
    """
    Download files whose names match a glob pattern.

    remote_path must contain wildcard characters in its final component, e.g.
    'S3:bucket/prefix/data_*.csv'.  Directory structure is preserved relative
    to the parent directory of the pattern, unless flatten=True, when every
    file of a matched directory is placed directly in local_destination.
    With sync=True, local files not present in the remote (among the matched
    set) are deleted.
    """
    remote_dir, pattern = _split_glob_remote_path(remote_path)
    _, rclone = _rclone_for_config(config)

    # Preflight: list the parent directory and check whether any entry
    # (file or directory) matches the glob pattern.
    check = _run_quietly(rclone, ["lsjson", remote_dir])
    if check.returncode != 0:
        print_warning(f"Cannot access '{remote_dir}'")
        return
    entries = json.loads(check.stdout or "[]")
    matches = [e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)]
    if not matches:
        print_info(f"No matches for wildcard '{remote_path}'")
        return
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
    for entry, files in zip(matches, files_of_matches):
        src = _join_remote(remote_dir, entry["Name"])
        if flatten:
            _warn_of_flattened_collisions(files, flattened)
            if entry["IsDir"]:
                _download_each(rclone, files, src)
                continue
        dst = str(local_destination / entry["Name"])
        if entry["IsDir"]:
            result = _rclone_sync(rclone, src, dst) if sync else rclone.copy(src, dst)
        else:
            result = rclone.copy_to(src=src, dst=dst)
        if result.returncode != 0:
            error = f"Download failed for '{src}': {_rclone_error_detail(result)}"
            _record_downloads(files, src, "failed", error=error)
            raise RuntimeError(error)
        _record_downloads(files, src, "downloaded")


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
) -> None:
    """
    Download each (source, destination, size) to its own destination with
    'rclone copyto', recording each, and raising on the first that fails.
    """
    for source, destination, size in files:
        result = rclone.copy_to(src=source, dst=destination)
        if result.returncode != 0:
            error = f"Download failed for '{source}': {_rclone_error_detail(result)}"
            _record_downloads([(source, destination, size)], match, "failed", error)
            raise RuntimeError(error)
        _record_downloads([(source, destination, size)], match, "downloaded")


def download_files(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    flatten: bool = False,
    sync: bool = False,
    dry_run: bool = False,
    destination_is_item: bool = False,
) -> None:
    """
    Download from remote_path to local_destination.

    remote_path may be a single file, a directory, or include glob patterns
    (delegated to rclone).  With flatten=True, all remote files are placed
    directly in local_destination without preserving directory structure.
    With sync=True, local files not present in the remote are deleted.
    With destination_is_item=True, local_destination is the remote item's own
    path rather than a directory to copy it into, so a single file is written
    to that path itself.
    """
    if flatten and sync:
        print_warning("--sync is not supported with --flatten; ignoring --sync")
        sync = False

    if dry_run:
        action = "sync" if sync else "download"
        if is_glob(remote_path):
            remote_dir, matches = list_remote_glob(config, remote_path)
            if not matches:
                print_info(f"No wildcard matches for '{remote_path}'")
                return
            names = [f"'{e['Name'] + ('/' if e['IsDir'] else '')}'" for e in matches]
            print_dry_run(
                f"Would {action} {len(matches)} matched item(s)"
                f" → '{local_destination}': {', '.join(names)}"
            )
            if json_requested() or flatten:
                _, rclone = _rclone_for_config(config)
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
        else:
            listing = list_remote(config, remote_path)
            if not listing.dirs and not listing.files:
                print_warning(f"'{remote_path}' does not exist")
                return
            n_files = len(listing.files)
            n_dirs = len(listing.dirs)
            ies = "y" if n_dirs == 1 else "ies"
            print_dry_run(
                f"Would {action} '{remote_path}' → '{local_destination}'"
                f" ({n_files} file(s), {n_dirs} director{ies})"
            )
            if json_requested() or flatten:
                _, rclone = _rclone_for_config(config)
                files = _literal_download_files(
                    rclone, remote_path, local_destination, flatten, destination_is_item
                )
                if flatten:
                    _warn_of_flattened_collisions(files, {})
                _record_downloads(files, remote_path, "would download")
        return

    if is_glob(remote_path):
        _download_with_glob(
            config, remote_path, local_destination, sync=sync, flatten=flatten
        )
        return

    listing = list_remote(config, remote_path)
    if not listing.dirs and not listing.files:
        print_warning(f"'{remote_path}' does not exist")
        return

    _, rclone = _rclone_for_config(config)
    dst = str(local_destination)

    is_file = _is_remote_file(rclone, remote_path)
    if destination_is_item and is_file:
        # 'rclone copy' would treat the path as a directory to copy into
        files = (
            _download_files_of(rclone, remote_path, False, local_destination)
            if json_requested()
            else []
        )
        print_info(f"Downloading '{remote_path}' → '{local_destination}'")
        result = rclone.copy_to(src=remote_path, dst=dst)
        if result.returncode != 0:
            error = f"Download failed: {_rclone_error_detail(result)}"
            _record_downloads(files, remote_path, "failed", error=error)
            raise RuntimeError(error)
        _record_downloads(files, remote_path, "downloaded")
    elif flatten and not is_file:
        # Each file of the tree to its own name directly in the destination
        print_info(f"Downloading (flat) '{remote_path}' → '{local_destination}'")
        files = _download_files_of(
            rclone, remote_path, True, local_destination, flatten=True
        )
        _warn_of_flattened_collisions(files, {})
        local_destination.mkdir(parents=True, exist_ok=True)
        _download_each(rclone, files, remote_path)
    else:
        files = (
            _literal_download_files(
                rclone, remote_path, local_destination, flatten, destination_is_item
            )
            if json_requested()
            else []
        )
        action = "Syncing" if sync else "Downloading"
        print_info(f"{action} '{remote_path}' → '{local_destination}'")
        if sync:
            result = _rclone_sync(rclone, src=remote_path, dst=dst)
        else:
            result = rclone.copy(src=remote_path, dst=dst)
        if result.returncode != 0:
            # One rclone run fetched them all, so which of them failed is unknown
            error = f"Download failed: {_rclone_error_detail(result)}"
            _record_downloads(files, remote_path, "failed", error=error)
            raise RuntimeError(error)
        _record_downloads(files, remote_path, "downloaded")


def _literal_download_files(
    rclone: Rclone,
    remote_path: str,
    local_destination: Path,
    flatten: bool,
    destination_is_item: bool = False,
) -> list[tuple[str, str, int | None]]:
    """
    The files a download of a literal (not wildcard) remote path fetches:
    a file to the destination itself when that is the item's own path, and
    otherwise inside the destination directory, under its own name, as
    'rclone copy' puts it; a directory's contents in the destination.
    """
    if _is_remote_file(rclone, remote_path):
        if destination_is_item:
            return _download_files_of(rclone, remote_path, False, local_destination)
        name = remote_path.rstrip("/").rsplit("/", 1)[-1]
        return _download_files_of(rclone, remote_path, False, local_destination / name)
    return _download_files_of(
        rclone, remote_path, True, local_destination, flatten=flatten
    )


def _delete_with_glob(
    config: ConfigDataClient,
    remote_path: str,
    recursive: bool = False,
) -> None:
    """
    Delete remote entries whose names match a glob pattern.

    Files are deleted directly; directories require recursive=True (matching
    the behaviour of non-glob delete).
    """
    remote_dir, pattern = _split_glob_remote_path(remote_path)
    _, rclone = _rclone_for_config(config)

    check = _run_quietly(rclone, ["lsjson", remote_dir])
    if check.returncode != 0:
        print_warning(f"Cannot access '{remote_dir}'")
        return
    entries = json.loads(check.stdout or "[]")
    matches = [e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)]
    if not matches:
        print_info(f"No matches for wildcard '{remote_path}'")
        return

    for entry in matches:
        entry_path = _join_remote(remote_dir, entry["Name"])
        is_dir = bool(entry["IsDir"])
        if is_dir:
            if recursive:
                print_info(f"Deleting directory '{entry_path}'")
                result = rclone.purge(entry_path)
            else:
                print_warning(
                    f"'{entry_path}' is a directory; use --recursive to delete it"
                )
                continue
        else:
            print_info(f"Deleting '{entry_path}'")
            result = rclone.delete_files(entry_path)
        if result.returncode != 0:
            error = f"Delete failed: {_rclone_error_detail(result)}"
            _record_deletion(entry_path, is_dir, "failed", error=error)
            raise RuntimeError(error)
        _record_deletion(entry_path, is_dir, "deleted")


def delete_remote(
    config: ConfigDataClient,
    remote_path: str,
    recursive: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Delete a remote file or, with recursive=True, a directory tree.
    """
    if dry_run:
        action = "recursively delete" if recursive else "delete"
        if is_glob(remote_path):
            remote_dir, matches = list_remote_glob(config, remote_path)
            if not matches:
                print_info(f"No wildcard matches for '{remote_path}'")
                return
            # As the deletion itself does, pass over a directory without
            # '--recursive'
            deletable = []
            for entry in matches:
                if entry["IsDir"] and not recursive:
                    print_warning(
                        f"'{_join_remote(remote_dir, entry['Name'])}' is a"
                        " directory; use --recursive to delete it"
                    )
                else:
                    deletable.append(entry)
            if not deletable:
                return
            names = [f"'{entry_to_name(e)}'" for e in deletable]
            print_dry_run(
                f"Would {action} {len(deletable)} matched item(s): {', '.join(names)}"
            )
            for entry in deletable:
                _record_deletion(
                    _join_remote(remote_dir, entry["Name"]),
                    bool(entry["IsDir"]),
                    "would delete",
                )
        else:
            listing = list_remote(config, remote_path)
            if not listing.dirs and not listing.files:
                print_warning(f"'{remote_path}' does not exist")
                return
            _, rclone = _rclone_for_config(config)
            is_file = _is_remote_file(rclone, remote_path)
            if not is_file and not recursive:
                print_warning(
                    f"'{remote_path}' is a directory; use --recursive to delete it"
                )
                return
            if is_file:
                print_dry_run(f"Would delete '{remote_path}'")
            else:
                rec_listing = list_remote(config, remote_path, recursive=True)
                n_files = len(rec_listing.files)
                n_dirs = len(rec_listing.dirs)
                ies = "y" if n_dirs == 1 else "ies"
                print_dry_run(
                    f"Would {action} '{remote_path}'"
                    f" ({n_files} file(s), {n_dirs} subdirector{ies})"
                )
            _record_deletion(remote_path, not is_file, "would delete")
        return

    if is_glob(remote_path):
        _delete_with_glob(config, remote_path, recursive=recursive)
        return

    _, rclone = _rclone_for_config(config)

    listing = list_remote(config, remote_path)
    if not listing.dirs and not listing.files:
        print_warning(f"'{remote_path}' does not exist")
        return

    # Classify by listing the parent directory: a basename comparison against
    # the path's own listing misclassifies a directory containing a single
    # same-named file (e.g. 'foo/foo')
    is_file = _is_remote_file(rclone, remote_path)

    if is_file:
        print_info(f"Deleting '{remote_path}'")
        result = rclone.delete_files(remote_path)
    elif recursive:
        print_info(f"Deleting directory '{remote_path}'")
        result = rclone.purge(remote_path)
    else:
        print_warning(f"'{remote_path}' is a directory; use --recursive to delete it")
        return

    if result.returncode != 0:
        error = f"Delete failed: {_rclone_error_detail(result)}"
        _record_deletion(remote_path, not is_file, "failed", error=error)
        raise RuntimeError(error)
    _record_deletion(remote_path, not is_file, "deleted")


def list_remote_glob(
    config: ConfigDataClient,
    remote_path: str,
) -> tuple[str, list[dict]]:
    """
    List entries in the parent directory whose names match the glob in remote_path.

    Returns (remote_dir, matching_entries) where each entry is an rclone lsjson
    dict with keys including Name, IsDir, Size, ModTime.
    """
    remote_dir, pattern = _split_glob_remote_path(remote_path)
    _, rclone = _rclone_for_config(config)
    check = _run_quietly(rclone, ["lsjson", remote_dir])
    if check.returncode != 0:
        return remote_dir, []
    entries = json.loads(check.stdout or "[]")
    return remote_dir, [e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)]


def lsjson_listing(
    config: ConfigDataClient, remote_path: str, recursive: bool = False
) -> list[dict]:
    """
    yd-ls's listing under '--json': rclone's 'lsjson' entries for
    'remote_path', each reduced to LSJSON_KEYS. A wildcard path gives the
    matching entries of its parent directory -- with a matching directory's
    contents too when recursive, their 'Path' relative to that parent, as
    rclone's own recursive listing of the parent would give it.
    """
    _, rclone = _rclone_for_config(config)
    if not is_glob(remote_path):
        entries = _lsjson(rclone, remote_path, recursive=recursive)
    else:
        remote_dir, matches = list_remote_glob(config, remote_path)
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


def _is_remote_file(rclone: Rclone, remote_path: str) -> bool:
    """
    Return True if remote_path resolves to a single file (not a directory).
    Lists the parent directory and checks whether the final path component
    appears as a non-directory entry.
    """
    path = remote_path.rstrip("/")
    path_part = path.split(":", 1)[-1]  # strip remote: prefix for the check
    if "/" not in path_part:
        return False
    parent, name = path.rsplit("/", 1)
    check = _run_quietly(rclone, ["lsjson", parent])
    if check.returncode != 0:
        return False
    entries = json.loads(check.stdout or "[]")
    matching = [e for e in entries if e["Name"] == name]
    return bool(matching) and not matching[0]["IsDir"]


def copy_remote(
    src_config: ConfigDataClient,
    src_path: str,
    dst_config: ConfigDataClient,
    dst_path: str,
    sync: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Copy from src_path to dst_path across (potentially different) remotes.
    With sync=True, the destination is made to mirror the source.
    When the source is a single file and the destination does not end with
    '/', uses rclone copyto so the destination filename is preserved
    (enabling file-to-file rename).
    """
    if dry_run:
        action = "sync" if sync else "copy"
        print_dry_run(f"Would {action} '{src_path}' → '{dst_path}'")
        if not json_requested():
            return

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

    src_is_file = not sync and _is_remote_file(rclone, src_path)
    # Source is a single file: use copyto for precise destination naming.
    # If dst ends with '/', treat it as a directory and append the source filename.
    dst_file = (
        dst_path + src_path.rsplit("/", 1)[-1] if dst_path.endswith("/") else dst_path
    )

    # Each file copied, named by the paths as the user gave them rather than
    # by the collision-free names the transfer used
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
        files = [
            (
                _renamed(source, src_name, src_orig_name),
                _renamed(destination, dst_name, dst_orig_name),
                size,
            )
            for source, destination, size in files
        ]

    if dry_run:
        for source, destination, size in files:
            record_transfer(source, destination, size, "would copy")
        return

    action = "Syncing" if sync else "Copying"
    print_info(f"{action} '{src_path}' → '{dst_path}'")

    if sync:
        result = _rclone_sync(rclone, src=src_path, dst=dst_path)
    elif src_is_file:
        result = rclone.copy_to(src=src_path, dst=dst_file)
    else:
        result = rclone.copy(src=src_path, dst=dst_path)

    if result.returncode != 0:
        # One rclone run copied them all, so which of them failed is unknown
        error = f"Copy failed: {_rclone_error_detail(result)}"
        for source, destination, size in files:
            record_transfer(source, destination, size, "failed", error=error)
        raise RuntimeError(error)
    for source, destination, size in files:
        record_transfer(source, destination, size, "copied")


def _renamed(path: str, name: str, new_name: str) -> str:
    """
    'path' with its remote prefix 'name:' replaced by 'new_name:'.
    """
    if name != new_name and path.startswith(f"{name}:"):
        return f"{new_name}:{path[len(name) + 1 :]}"
    return path
