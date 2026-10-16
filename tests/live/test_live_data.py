"""
Live: the data client against the run's prefix: upload, list, download (the
bytes unchanged), copy and delete; and a path that does not exist, which a
bucket-based remote answers as an empty directory. Needs [data] and AWS as
the primary with an instance profile; skipped otherwise, and the gate leaves
the data verbs out.
"""

import secrets

import pytest
from harness import data

pytestmark = [pytest.mark.live, pytest.mark.xdist_group("ydst-data")]


@pytest.fixture
def data_run(live_run):
    reason = data.unavailable(live_run.run.config)
    if reason:
        pytest.skip(reason)
    return live_run


def test_upload_list_download_copy_delete(data_run, tmp_path):
    yd = data_run.yd
    payload = secrets.token_bytes(4096)
    source = tmp_path / "payload.bin"
    source.write_bytes(payload)

    yd("data", "upload", str(source), "--json", "--quiet")
    listed = yd("data", "ls", "--json", "--quiet").records
    assert "payload.bin" in {r.get("Name") for r in listed}

    into = tmp_path / "down"
    into.mkdir()
    yd("data", "download", "payload.bin", "--into", str(into), "--json", "--quiet")
    assert (into / "payload.bin").read_bytes() == payload

    yd("data", "copy", "payload.bin", "copied.bin", "--json", "--quiet")
    names = {r.get("Name") for r in yd("data", "ls", "--json", "--quiet").records}
    assert {"payload.bin", "copied.bin"} <= names

    yd("data", "delete", "payload.bin", "copied.bin", "--yes", "--json", "--quiet")
    # An emptied prefix may no longer exist, which 'ls' reports as exit 1
    left = yd("data", "ls", "--json", "--quiet", ok=(0, 1)).records
    assert not {"payload.bin", "copied.bin"} & {r.get("Name") for r in left}, left


def test_a_missing_path_on_the_bucket(data_run, tmp_path):
    """
    S3 answers rclone's stat of any path that is not an object with an
    unnamed directory, whether anything is stored under it or not
    (operations.remote_stat()), which read once as an empty directory to
    all three commands. Listing it is an empty listing, as an empty prefix
    is; downloading it fails, naming it; deleting it is nothing to do.
    """
    yd = data_run.yd
    missing = f"no-such-path-{secrets.token_hex(4)}"

    assert yd("data", "ls", missing, "--json", "--quiet").records == []

    into = tmp_path / "down"
    into.mkdir()
    downloaded = yd(
        "data",
        "download",
        missing,
        "--into",
        str(into),
        "--json",
        "--quiet",
        ok=(1,),
        expected_failure=True,
    )
    shown = downloaded.stderr
    assert missing in shown and "does not exist" in shown, yd.describe(downloaded)
    assert not any(into.iterdir())

    deleted = yd("data", "delete", missing, "--yes", "--json", "--quiet")
    (record,) = deleted.records
    assert record["action"] == "skipped", record
    assert "is a directory" not in deleted.stdout + deleted.stderr
