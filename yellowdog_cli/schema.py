#!/usr/bin/env python3

"""
Print, write or check the specification schemas: what yd-submit, yd-provision,
yd-instantiate, yd-create and yd-nodeaction accept, generated from the
registry and the installed SDK (utils/spec_schema.py).

Built on neither wrapper: yd-schema needs no configuration and no
credentials, so it is a registry command on ARGS_PARSER alone, like
doctor.py.
"""

import json
from pathlib import Path
from sys import exit

from yellowdog_client._version import __version__ as sdk_version

from yellowdog_cli._version import __version__ as cli_version
from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import (
    print_error,
    print_info,
    print_json,
    print_simple,
)
from yellowdog_cli.utils.spec_schema import Family, SchemaGenerationError, build_schema

INDEX_FILE = "index.json"


def _schema_filename(family: Family) -> str:
    return f"{family.value}.schema.json"


def _write_json(path: Path, document: dict) -> None:
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write(directory: str) -> int:
    """
    Every family's schema, plus an index.json naming the versions that built
    them: 0, or 1 having reported a directory or file that cannot be written.

    The index is written last, so a failure part-way leaves the directory
    with no index, or with the previous one: --check then reports it
    unreadable or stale rather than up to date.
    """
    target = Path(directory)
    try:
        target.mkdir(parents=True, exist_ok=True)
        families: dict[str, str] = {}
        for family in Family:
            filename = _schema_filename(family)
            _write_json(target / filename, build_schema(family))
            families[family.value] = filename
            print_info(f"wrote {target / filename}")
        index = {"cli": cli_version, "sdk": sdk_version, "families": families}
        _write_json(target / INDEX_FILE, index)
        print_info(f"wrote {target / INDEX_FILE}")
    except OSError as error:
        path = error.filename or target
        print_error(f"{path}: cannot write ({error.strerror or error})")
        return 1
    return 0


def _check(directory: str) -> int:
    """
    0 if <directory>'s index.json names the installed CLI and SDK versions,
    else 1, printing which changed and how to fix it.
    """
    index_path = Path(directory) / INDEX_FILE
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        written_cli = index["cli"]
        written_sdk = index["sdk"]
    except (OSError, json.JSONDecodeError, KeyError) as error:
        print_error(f"{index_path}: cannot be read ({error})")
        return 1
    if written_cli == cli_version and written_sdk == sdk_version:
        print_simple(
            f"up to date: CLI {cli_version}, SDK {sdk_version}", override_quiet=True
        )
        return 0
    print_error(
        f"written for CLI {written_cli} / SDK {written_sdk}, now {cli_version} /"
        f" {sdk_version}: run yd-schema --write {directory}"
    )
    return 1


def main() -> None:
    try:
        if ARGS_PARSER.schema_list:
            for family in Family:
                print_simple(family.value, override_quiet=True)
            return
        if ARGS_PARSER.schema_write_dir is not None:
            exit(_write(ARGS_PARSER.schema_write_dir))
        if ARGS_PARSER.schema_check_dir is not None:
            exit(_check(ARGS_PARSER.schema_check_dir))
        family = Family(ARGS_PARSER.schema_family)
        print_json(build_schema(family))
    except SchemaGenerationError as error:
        print_error(str(error))
        exit(1)


if __name__ == "__main__":
    main()
