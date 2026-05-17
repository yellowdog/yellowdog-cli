#!/usr/bin/env python3

"""
List files and directories in a remote data client.
"""

from collections import defaultdict

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.config_types import ConfigDataClient
from yellowdog_cli.utils.dataclient_utils import (
    is_glob,
    list_remote,
    list_remote_glob,
    resolve_remote_path,
)
from yellowdog_cli.utils.dataclient_wrapper import dataclient_wrapper
from yellowdog_cli.utils.load_config import load_config_data_client
from yellowdog_cli.utils.printing import print_info, print_simple
from yellowdog_cli.utils.rclone_utils import upgrade_rclone, which_rclone

CONFIG_DATA_CLIENT: ConfigDataClient = load_config_data_client()

_ZERO_MODTIME_PREFIX = "0001-"


def _fmt_size(size: int | None) -> str:
    if size is None or size < 0:
        return "-"
    return f"{size:,}"


def _fmt_modtime(mod_time: str | None) -> str:
    if not mod_time or mod_time.startswith(_ZERO_MODTIME_PREFIX):
        return "-"
    # Strip sub-second precision and trailing Z
    return mod_time.split(".")[0].rstrip("Z")


def _ls_glob(config: ConfigDataClient, remote_path: str, recursive: bool) -> None:
    """
    List remote entries whose names match a glob pattern.

    Non-recursive: show matching files and directories as a flat table.
    Recursive: show matching files inline; show matching directories as trees.
    """
    remote_dir, matches = list_remote_glob(config, remote_path)
    if not matches:
        print_simple("  (no wildcard matches)")
        return

    base = remote_dir.rstrip("/")

    long = ARGS_PARSER.long_listing or False
    if not recursive:
        entries = []
        for e in matches:
            if e["IsDir"]:
                entries.append(("DIR", e["Name"] + "/", ""))
            else:
                size = _fmt_size(e.get("Size")) if long else ""
                entries.append(
                    (size, e["Name"], _fmt_modtime(e.get("ModTime")) if long else "")
                )
        if long:
            max_size_w = max(len(e[0]) for e in entries)
            max_name_w = max(len(e[1]) for e in entries)
            for size, name, mod_time in entries:
                line = (
                    f"  {size:>{max_size_w}}  {name:<{max_name_w}}  {mod_time}".rstrip()
                )
                print_simple(line, override_quiet=True)
        else:
            for _, name, _ in entries:
                print_simple(f"  {name}", override_quiet=True)
    else:
        for e in matches:
            entry_path = f"{base}/{e['Name']}"
            if e["IsDir"]:
                print_simple(f"{e['Name']}/", override_quiet=True)
                sub_listing = list_remote(config, entry_path, recursive=True)
                if sub_listing.dirs or sub_listing.files:
                    _print_tree(sub_listing)
            else:
                if long:
                    line = f"{e['Name']}  {_fmt_size(e.get('Size'))}  {_fmt_modtime(e.get('ModTime'))}".rstrip()
                else:
                    line = e["Name"]
                print_simple(line, override_quiet=True)


@dataclient_wrapper
def main():

    if ARGS_PARSER.upgrade_rclone:
        upgrade_rclone()
        return

    if ARGS_PARSER.which_rclone:
        which_rclone()
        return

    recursive = ARGS_PARSER.recursive or False
    remote_paths = ARGS_PARSER.remote_paths or []

    if not remote_paths:
        # Default to the configured prefix
        remote_paths = [resolve_remote_path(CONFIG_DATA_CLIENT)]

    for remote_path_str in remote_paths:
        remote_path = resolve_remote_path(
            CONFIG_DATA_CLIENT, relative_path=remote_path_str
        )
        print_info(f"Listing '{remote_path}'")
        if is_glob(remote_path):
            _ls_glob(CONFIG_DATA_CLIENT, remote_path, recursive=recursive)
        else:
            listing = list_remote(CONFIG_DATA_CLIENT, remote_path, recursive=recursive)
            _print_listing(listing, recursive=recursive)


def _print_listing(listing, recursive: bool = False) -> None:

    if not listing.dirs and not listing.files:
        print_simple("  (empty)")
        return
    if recursive:
        _print_tree(listing)
    else:
        _print_flat(listing)


def _print_flat(listing) -> None:

    long = ARGS_PARSER.long_listing or False
    entries = []
    for d in listing.dirs:
        entries.append(("DIR", d.name + "/", ""))
    for f in listing.files:
        size = _fmt_size(f.path.size) if long else ""
        mod_time = _fmt_modtime(f.path.mod_time) if long else ""
        entries.append((size, f.name, mod_time))

    if long:
        max_size_w = max(len(e[0]) for e in entries)
        max_name_w = max(len(e[1]) for e in entries)
        for size, name, mod_time in entries:
            line = f"  {size:>{max_size_w}}  {name:<{max_name_w}}  {mod_time}".rstrip()
            print_simple(line, override_quiet=True)
    else:
        for _, name, _ in entries:
            print_simple(f"  {name}", override_quiet=True)


def _find_base_prefix(listing) -> str:
    """
    Return the common parent path shared by all entries in the listing
    (i.e. the path of the directory that was listed).
    """
    all_paths = [d.path.path for d in listing.dirs] + [
        f.path.path for f in listing.files
    ]
    if not all_paths:
        return ""
    # Split each full path into components and drop the last (the entry name
    # itself) to get the parent.  Then find the longest common prefix of those
    # parent component lists.
    split_parents = [p.split("/")[:-1] for p in all_paths]
    common = split_parents[0]
    for parts in split_parents[1:]:
        i = 0
        while i < len(common) and i < len(parts) and common[i] == parts[i]:
            i += 1
        common = common[:i]
    return "/".join(common)


def _print_tree(listing) -> None:
    """
    Print a recursive listing as an indented tree using box-drawing characters.
    """
    base_prefix = _find_base_prefix(listing)
    prefix_len = len(base_prefix) + (1 if base_prefix else 0)  # +1 for the "/"

    # Build parent_rel_path → [(is_dir, name, rel_path, size, mod_time)]
    children: dict[str, list] = defaultdict(list)
    for d in listing.dirs:
        rel_path = d.path.path[prefix_len:]
        parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        children[parent].append((True, d.name, rel_path, None, None))
    for f in listing.files:
        rel_path = f.path.path[prefix_len:]
        parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
        children[parent].append((False, f.name, rel_path, f.path.size, f.path.mod_time))

    def _render(parent_rel: str, prefix: str) -> None:
        items = children.get(parent_rel, [])
        dirs = sorted([e for e in items if e[0]], key=lambda e: e[1])
        files = sorted([e for e in items if not e[0]], key=lambda e: e[1])
        all_items = dirs + files
        for i, (is_dir, name, rel_path, size, mod_time) in enumerate(all_items):
            is_last = i == len(all_items) - 1
            connector = "└── " if is_last else "├── "
            child_prefix = prefix + ("    " if is_last else "│   ")
            if is_dir:
                print_simple(f"{prefix}{connector}{name}/", override_quiet=True)
                _render(rel_path, child_prefix)
            else:
                if ARGS_PARSER.long_listing:
                    size_str = _fmt_size(size)
                    mod_time_str = _fmt_modtime(mod_time)
                    line = f"{prefix}{connector}{name}  {size_str}  {mod_time_str}".rstrip()
                else:
                    line = f"{prefix}{connector}{name}"
                print_simple(line, override_quiet=True)

    _render("", "")


if __name__ == "__main__":
    main()
