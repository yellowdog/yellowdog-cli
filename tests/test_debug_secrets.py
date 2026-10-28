"""
The '--debug' trace never holds a credential: the configured key and
secret, a secret-named variable's value, or the keys inside an inline rclone
remote. Each command runs as a user would run it, in a subprocess with a
configuration of the test's own, its stdout and stderr both searched; the
Platform is a local server that refuses every request, so a failure's
traceback is traced too, and nothing reaches the real Platform.
"""

import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

KEY = "KEY-4f9c2a7e1b"
SECRET = "SECRET-8d3e6b0f5a"
TOKEN = "TOKEN-2c7a9e4d1f"
REMOTE_KEY = "REMOTE-KEY-6b1d8f3a9c"
REMOTE_SECRET = "REMOTE-SECRET-0e5c2a7d4b"
CREDENTIALS = (KEY, SECRET, TOKEN, REMOTE_KEY, REMOTE_SECRET)

CONFIG = f"""
[common]
namespace = "image-processing"
tag = "render"

[common.variables]
api_token = "{TOKEN}"

[dataClient]
remote = ":s3,provider=Other,access_key_id={REMOTE_KEY},secret_access_key={REMOTE_SECRET}:"
bucket = "renders"

[workRequirement]
taskType = "bash"
arguments = ["-c", "echo {{{{api_token}}}}"]
taskCount = 2
"""


class _Refusing(BaseHTTPRequestHandler):
    def _refuse(self) -> None:
        self.send_response(401)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_PUT = do_DELETE = _refuse

    def log_message(self, format, *args) -> None:
        pass


@pytest.fixture(scope="module")
def platform_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Refusing)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _run(args: list[str], tmp_path, url: str) -> subprocess.CompletedProcess:
    (tmp_path / "config.toml").write_text(CONFIG, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
    env.update({"YD_KEY": KEY, "YD_SECRET": SECRET, "YD_URL": url})
    return subprocess.run(
        [sys.executable, "-m", "yellowdog_cli.yd", *args, "--debug"],
        capture_output=True,
        encoding="utf-8",
        env=env,
        cwd=tmp_path,
        timeout=120,
    )


@pytest.mark.parametrize(
    "args",
    [
        ["workrequirement", "submit", "--dry-run"],
        ["workrequirement", "submit", "--dry-run", "--json"],
        ["workerpool", "list"],  # refused: the failure's traceback is traced
        ["variables"],
        ["variables", "api_token"],
        # Offline: its other checks reach PyPI and the remote's bucket
        ["doctor", "--offline"],
    ],
    ids=lambda args: " ".join(args),
)
def test_no_credential_is_traced(args, tmp_path, platform_url):
    result = _run(args, tmp_path, platform_url)
    trace = result.stderr
    # yd doctor loads the configuration with its output captured, so its
    # preamble is not traced
    if args[0] != "doctor":
        assert "DEBUG : " in trace, trace
    for credential in CREDENTIALS:
        # The dry run prints the Task's arguments, which hold the token by
        # design: only the trace is held to it
        assert credential not in trace, credential
    # yd doctor shows the key by design, and withholds the secret
    for credential in (SECRET, REMOTE_KEY, REMOTE_SECRET):
        assert credential not in result.stdout, credential


def test_a_request_is_traced(tmp_path, platform_url):
    result = _run(["workerpool", "list"], tmp_path, platform_url)
    assert result.returncode == 4  # the refusal's own exit code
    assert '"GET /workerPools/' in result.stderr
    assert "Traceback (most recent call last):" in result.stderr
