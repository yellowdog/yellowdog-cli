"""
Offline tests for matched_item_rows(), the enumeration behind both
'yd-delete --dry-run --json' and 'yd-download --dry-run --json'. Its output is
Commander's only handle on a matched object, so each row must carry a path that
can be passed straight back to a delete or a download — and must be joined to the
parent directory it actually came from. The pre-existing coverage of the delete
half was a system test needing storage credentials.

These target dataclient_utils directly, because that is where the row building
now looks up resolve_remote_path and list_remote_glob; patching them on the
command modules would have no effect.
"""

from yellowdog_cli.utils import dataclient_utils
from yellowdog_cli.utils.dataclient_utils import entry_to_name, matched_item_rows

# The stubs below ignore the config argument entirely, so any sentinel will do.
CONFIG = object()


def test_entry_to_name_marks_directories():
    assert entry_to_name({"Name": "file.txt", "IsDir": False}) == "file.txt"
    assert entry_to_name({"Name": "subdir", "IsDir": True}) == "subdir/"


def _rows(monkeypatch, resolved_to_entries: dict, remote_paths: list[str]):
    """
    Call matched_item_rows with the two remote-touching helpers stubbed.
    'resolved_to_entries' maps a resolved remote path to the (remote_dir, entries)
    that list_remote_glob should yield for it.
    """
    monkeypatch.setattr(
        dataclient_utils,
        "resolve_remote_path",
        lambda config, relative_path=None: relative_path,
    )
    monkeypatch.setattr(
        dataclient_utils,
        "list_remote_glob",
        lambda config, remote_path: resolved_to_entries[remote_path],
    )
    return matched_item_rows(CONFIG, remote_paths)  # type: ignore[arg-type]


def test_row_carries_name_path_and_isdir(monkeypatch):
    rows = _rows(
        monkeypatch,
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


def test_bucket_root_path_has_no_double_separator(monkeypatch):
    # _split_glob_remote_path yields just 'S3:' when there is no '/' in the path
    # part, so a naive join would produce 'S3:/thing'.
    rows = _rows(
        monkeypatch,
        {"S3:pyex*": ("S3:", [{"Name": "pyex-001", "IsDir": False}])},
        ["S3:pyex*"],
    )
    assert rows[0]["path"] == "S3:pyex-001"


def test_each_entry_is_joined_to_its_own_parent(monkeypatch):
    # Flattening all the basenames first and then joining them to one parent would
    # attribute an object to the wrong directory — and the caller would then delete
    # or download the wrong path.
    rows = _rows(
        monkeypatch,
        {
            "S3:bucket/a/*": ("S3:bucket/a/", [{"Name": "one", "IsDir": False}]),
            "S3:bucket/b/*": ("S3:bucket/b/", [{"Name": "two", "IsDir": False}]),
        },
        ["S3:bucket/a/*", "S3:bucket/b/*"],
    )
    assert [row["path"] for row in rows] == ["S3:bucket/a/one", "S3:bucket/b/two"]


def test_no_matches_gives_no_rows(monkeypatch):
    rows = _rows(
        monkeypatch, {"S3:bucket/none*": ("S3:bucket/", [])}, ["S3:bucket/none*"]
    )
    assert rows == []


def test_no_remote_paths_enumerates_the_configured_prefix(monkeypatch):
    # With no paths given, the configured prefix is enumerated — resolve_remote_path
    # is called with no relative_path, which the stub renders as None.
    rows = _rows(
        monkeypatch,
        {None: ("S3:bucket/pfx/", [{"Name": "only", "IsDir": False}])},
        [],
    )
    assert [row["path"] for row in rows] == ["S3:bucket/pfx/only"]
