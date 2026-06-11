"""
Utility functions for rclone-backed data client commands:
yd-upload, yd-download, yd-delete, yd-ls.
"""

import fnmatch
import json
from pathlib import Path
from typing import cast

from rclone_api import Config, Rclone
from rclone_api.dir_listing import DirListing

from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.printing import print_info, print_warning
from yellowdog_cli.utils.rclone_utils import (
    make_rclone,
    make_rclone_for_copy,
    parse_rclone_config,
)
from yellowdog_cli.utils.variables import process_variable_substitutions

_GLOB_CHARS = frozenset("*?[")


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

    if relative_path is not None:
        relative_path = cast(str, process_variable_substitutions(relative_path))
    if filename is not None:
        filename = cast(str, process_variable_substitutions(filename))

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
    if dry_run:
        print_info(f"Dry-run: Would upload '{local_path}' → '{remote_path}'")
        return

    _, rclone = _rclone_for_config(config)
    print_info(f"Uploading '{local_path}' → '{remote_path}'")
    result = rclone.copy_to(src=str(local_path.resolve()), dst=remote_path)
    if result.returncode != 0:
        raise RuntimeError(f"Upload failed: {result.stderr}")


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

    action = "sync" if sync else "copy"
    if dry_run:
        print_info(
            f"Dry-run: Would {action} directory '{local_path}' → '{remote_path}'"
        )
        return

    _, rclone = _rclone_for_config(config)
    print_info(f"{'Syncing' if sync else 'Uploading'} '{local_path}' → '{remote_path}'")
    if sync:
        result = _rclone_sync(rclone, src=str(local_path.resolve()), dst=remote_path)
    else:
        result = rclone.copy(src=str(local_path.resolve()), dst=remote_path)
    if result.returncode != 0:
        raise RuntimeError(f"Directory upload failed: {result.stderr}")


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

    for local_file in files:
        dest = f"{remote_path.rstrip('/')}/{local_file.name}"
        upload_file(config, local_file, dest, dry_run=dry_run)


def is_glob(path: str) -> bool:
    """
    Return True if path contains glob wildcard characters (*  ?  [).
    Only the path component after the remote: prefix is checked.
    """
    path_part = path.split(":", 1)[-1] if ":" in path else path
    return bool(_GLOB_CHARS.intersection(path_part))


def _split_glob_remote_path(remote_path: str) -> tuple[str, str]:
    """
    Split a glob remote path into (parent_dir, pattern).

    'S3:bucket/prefix/xxx*' → ('S3:bucket/prefix/', 'xxx*')
    'S3:bucket/xxx*'        → ('S3:bucket/', 'xxx*')
    """
    colon_idx = remote_path.find(":")
    remote_prefix = remote_path[: colon_idx + 1] if colon_idx >= 0 else ""
    path_part = remote_path[colon_idx + 1 :] if colon_idx >= 0 else remote_path

    if "/" in path_part:
        dir_part, pattern = path_part.rsplit("/", 1)
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
) -> None:
    """
    Download files whose names match a glob pattern.

    remote_path must contain wildcard characters in its final component, e.g.
    'S3:bucket/prefix/data_*.csv'.  Directory structure is preserved relative
    to the parent directory of the pattern.  With sync=True, local files not
    present in the remote (among the matched set) are deleted.
    """
    remote_dir, pattern = _split_glob_remote_path(remote_path)
    _, rclone = _rclone_for_config(config)

    # Preflight: list the parent directory and check whether any entry
    # (file or directory) matches the glob pattern.
    check = rclone.impl._run(["lsjson", remote_dir], capture=True)
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
    cmd = "sync" if sync else "copy"
    result = rclone.impl._run(
        [
            cmd,
            remote_dir,
            str(local_destination),
            "--include",
            pattern,
            "--include",
            f"{pattern}/**",
            "--checkers",
            "1000",
            "--transfers",
            "32",
            "--low-level-retries",
            "10",
        ],
        capture=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Download failed: {result.stderr}")


def download_files(
    config: ConfigDataClient,
    remote_path: str,
    local_destination: Path,
    flatten: bool = False,
    sync: bool = False,
    dry_run: bool = False,
) -> None:
    """
    Download from remote_path to local_destination.

    remote_path may be a single file, a directory, or include glob patterns
    (delegated to rclone).  With flatten=True, all remote files are placed
    directly in local_destination without preserving directory structure.
    With sync=True, local files not present in the remote are deleted.
    """
    if flatten and sync:
        print_warning("--sync is not supported with --flatten; ignoring --sync")
        sync = False

    if dry_run:
        action = "sync" if sync else "download"
        if is_glob(remote_path):
            _, matches = list_remote_glob(config, remote_path)
            if not matches:
                print_info(f"No wildcard matches for '{remote_path}'")
                return
            names = [f"'{e['Name'] + ('/' if e['IsDir'] else '')}'" for e in matches]
            print_info(
                f"Dry-run: Would {action} {len(matches)} matched item(s)"
                f" → '{local_destination}': {', '.join(names)}"
            )
        else:
            listing = list_remote(config, remote_path)
            if not listing.dirs and not listing.files:
                print_warning(f"'{remote_path}' does not exist")
                return
            n_files = len(listing.files)
            n_dirs = len(listing.dirs)
            ies = "y" if n_dirs == 1 else "ies"
            print_info(
                f"Dry-run: Would {action} '{remote_path}' → '{local_destination}'"
                f" ({n_files} file(s), {n_dirs} director{ies})"
            )
        return

    if is_glob(remote_path):
        _download_with_glob(config, remote_path, local_destination, sync=sync)
        return

    listing = list_remote(config, remote_path)
    if not listing.dirs and not listing.files:
        print_warning(f"'{remote_path}' does not exist")
        return

    _, rclone = _rclone_for_config(config)
    dst = str(local_destination)

    if flatten:
        # Walk the remote path and download each file flat to the destination
        print_info(f"Downloading (flat) '{remote_path}' → '{local_destination}'")
        local_destination.mkdir(parents=True, exist_ok=True)
        for dir_listing in rclone.walk(remote_path):
            for f in dir_listing.files:
                file_dst = str(local_destination / f.name)
                result = rclone.copy_to(
                    src=f"{remote_path.rstrip('/')}/{f.path.path}", dst=file_dst
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"Download failed for '{f.path.path}': {result.stderr}"
                    )
    else:
        action = "Syncing" if sync else "Downloading"
        print_info(f"{action} '{remote_path}' → '{local_destination}'")
        if sync:
            result = _rclone_sync(rclone, src=remote_path, dst=dst)
        else:
            result = rclone.copy(src=remote_path, dst=dst)
        if result.returncode != 0:
            raise RuntimeError(f"Download failed: {result.stderr}")


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

    check = rclone.impl._run(["lsjson", remote_dir], capture=True)
    if check.returncode != 0:
        print_warning(f"Cannot access '{remote_dir}'")
        return
    entries = json.loads(check.stdout or "[]")
    matches = [e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)]
    if not matches:
        print_info(f"No matches for wildcard '{remote_path}'")
        return

    base = remote_dir.rstrip("/")
    for entry in matches:
        entry_path = f"{base}/{entry['Name']}"
        if entry["IsDir"]:
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
            raise RuntimeError(f"Delete failed: {result.stderr}")


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
            _, matches = list_remote_glob(config, remote_path)
            if not matches:
                print_info(f"No wildcard matches for '{remote_path}'")
                return
            names = [f"'{e['Name'] + ('/' if e['IsDir'] else '')}'" for e in matches]
            print_info(
                f"Dry-run: Would {action} {len(matches)} matched item(s):"
                f" {', '.join(names)}"
            )
        else:
            listing = list_remote(config, remote_path)
            if not listing.dirs and not listing.files:
                print_warning(f"'{remote_path}' does not exist")
                return
            basename = remote_path.rstrip("/").rsplit("/", 1)[-1].split(":")[-1]
            is_file = (
                not listing.dirs
                and len(listing.files) == 1
                and listing.files[0].name == basename
            )
            if not is_file and not recursive:
                print_warning(
                    f"'{remote_path}' is a directory; use --recursive to delete it"
                )
                return
            if is_file:
                print_info(f"Dry-run: Would delete '{remote_path}'")
            else:
                rec_listing = list_remote(config, remote_path, recursive=True)
                n_files = len(rec_listing.files)
                n_dirs = len(rec_listing.dirs)
                ies = "y" if n_dirs == 1 else "ies"
                print_info(
                    f"Dry-run: Would {action} '{remote_path}'"
                    f" ({n_files} file(s), {n_dirs} subdirector{ies})"
                )
        return

    if is_glob(remote_path):
        _delete_with_glob(config, remote_path, recursive=recursive)
        return

    _, rclone = _rclone_for_config(config)

    listing = list_remote(config, remote_path)
    if not listing.dirs and not listing.files:
        print_warning(f"'{remote_path}' does not exist")
        return

    # When rclone lists a single file, it returns that file itself in the
    # listing (name == basename of the path).  Distinguish this from a
    # directory whose *contents* are listed (names differ from the path).
    basename = remote_path.rstrip("/").rsplit("/", 1)[-1].split(":")[-1]
    is_file = (
        not listing.dirs
        and len(listing.files) == 1
        and listing.files[0].name == basename
    )

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
        raise RuntimeError(f"Delete failed: {result.stderr}")


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
    check = rclone.impl._run(["lsjson", remote_dir], capture=True)
    if check.returncode != 0:
        return remote_dir, []
    entries = json.loads(check.stdout or "[]")
    return remote_dir, [e for e in entries if fnmatch.fnmatchcase(e["Name"], pattern)]


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
    return rclone.ls(src=remote_path, max_depth=max_depth)


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
    check = rclone.impl._run(["lsjson", parent], capture=True)
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
        print_info(f"Dry-run: Would {action} '{src_path}' → '{dst_path}'")
        return

    src_remote_str = _require_remote(src_config)
    dst_remote_str = _require_remote(dst_config)

    src_orig_name, _ = parse_rclone_config(src_remote_str)
    dst_orig_name, _ = parse_rclone_config(dst_remote_str)
    src_name, dst_name, rclone = make_rclone_for_copy(src_remote_str, dst_remote_str)

    # Colliding remote names are renamed by make_rclone_for_copy; the paths
    # were resolved with the original names, so rewrite their prefixes
    if src_name != src_orig_name and src_path.startswith(f"{src_orig_name}:"):
        src_path = f"{src_name}:{src_path[len(src_orig_name) + 1 :]}"
    if dst_name != dst_orig_name and dst_path.startswith(f"{dst_orig_name}:"):
        dst_path = f"{dst_name}:{dst_path[len(dst_orig_name) + 1 :]}"

    action = "Syncing" if sync else "Copying"
    print_info(f"{action} '{src_path}' → '{dst_path}'")

    # Normalise shell tab-completion artefact: "dir/." → "dir/"
    if dst_path.endswith("/."):
        dst_path = dst_path[:-1]

    if sync:
        result = _rclone_sync(rclone, src=src_path, dst=dst_path)
    elif _is_remote_file(rclone, src_path):
        # Source is a single file: use copyto for precise destination naming.
        # If dst ends with '/', treat it as a directory and append the source filename.
        if dst_path.endswith("/"):
            dst_file = dst_path + src_path.rsplit("/", 1)[-1]
        else:
            dst_file = dst_path
        result = rclone.copy_to(src=src_path, dst=dst_file)
    else:
        result = rclone.copy(src=src_path, dst=dst_path)

    if result.returncode != 0:
        raise RuntimeError(f"Copy failed: {result.stderr}")
