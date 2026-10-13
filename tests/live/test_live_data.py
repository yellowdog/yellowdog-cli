"""
Live: the data client against the run's prefix: upload, list, download (the
bytes unchanged), copy and delete. Needs [data] and AWS as the primary with
an instance profile; skipped otherwise, and the gate leaves the data verbs out.
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
