"""
Offline tests for 'yd-delete -D --json'. Its output is Commander's only handle on
a matched object, so each row must carry a path that can be passed straight back
to a delete — and must be joined to the parent directory it actually came from.
The pre-existing coverage was a system test needing storage credentials.
"""

import json

from yellowdog_cli import delete
from yellowdog_cli.utils.dataclient_utils import entry_to_name


def test_entry_to_name_marks_directories():
    assert entry_to_name({"Name": "file.txt", "IsDir": False}) == "file.txt"
    assert entry_to_name({"Name": "subdir", "IsDir": True}) == "subdir/"


def _emit(monkeypatch, capsys, resolved_to_entries: dict, remote_paths: list[str]):
    """
    Drive _emit_matched_json with list_remote_glob stubbed. 'resolved_to_entries'
    maps a resolved remote path to the (remote_dir, entries) it should yield.
    Returns the parsed JSON array.
    """
    monkeypatch.setattr(
        delete, "resolve_remote_path", lambda config, relative_path=None: relative_path
    )
    monkeypatch.setattr(
        delete,
        "list_remote_glob",
        lambda config, remote_path: resolved_to_entries[remote_path],
    )
    # Discard any output already buffered from module imports (config loading writes
    # to stdout). We want only the output from the function call below.
    capsys.readouterr()
    delete._emit_matched_json(remote_paths)
    return json.loads(capsys.readouterr().out)


def test_row_carries_name_path_and_isdir(monkeypatch, capsys):
    rows = _emit(
        monkeypatch,
        capsys,
        {
            "S3:bucket/pfx/pyex*": (
                "S3:bucket/pfx/",
                [
                    {"Name": "pyex-001", "IsDir": False},
                    {"Name": "pyex-logs", "IsDir": True},
                ],
            )
        },
        ["S3:bucket/pfx/pyex*"],
    )
    assert rows == [
        {"name": "pyex-001", "path": "S3:bucket/pfx/pyex-001", "isDir": False},
        # the display name keeps its trailing '/', the path must not: a trailing
        # slash means directory-destination intent to resolve_remote_path
        {"name": "pyex-logs/", "path": "S3:bucket/pfx/pyex-logs", "isDir": True},
    ]


def test_bucket_root_path_has_no_double_separator(monkeypatch, capsys):
    # _split_glob_remote_path yields just 'S3:' when there is no '/' in the path
    # part, so a naive join would produce 'S3:/thing'.
    rows = _emit(
        monkeypatch,
        capsys,
        {"S3:pyex*": ("S3:", [{"Name": "pyex-001", "IsDir": False}])},
        ["S3:pyex*"],
    )
    assert rows[0]["path"] == "S3:pyex-001"


def test_each_entry_is_joined_to_its_own_parent(monkeypatch, capsys):
    # The regression this change could introduce: flattening all the basenames
    # first and then joining them to one parent would attribute an object to the
    # wrong directory — and a delete would then remove the wrong path.
    rows = _emit(
        monkeypatch,
        capsys,
        {
            "S3:bucket/a/*": ("S3:bucket/a/", [{"Name": "one", "IsDir": False}]),
            "S3:bucket/b/*": ("S3:bucket/b/", [{"Name": "two", "IsDir": False}]),
        },
        ["S3:bucket/a/*", "S3:bucket/b/*"],
    )
    assert [row["path"] for row in rows] == ["S3:bucket/a/one", "S3:bucket/b/two"]


def test_no_matches_emits_empty_array(monkeypatch, capsys):
    rows = _emit(
        monkeypatch,
        capsys,
        {"S3:bucket/none*": ("S3:bucket/", [])},
        ["S3:bucket/none*"],
    )
    assert rows == []
