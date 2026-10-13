"""
Running 'yd' for the live suite: arguments, environment, results, masking.
A stand-in program plays 'yd', so nothing here touches the Platform.
"""

import hashlib
import json
import sys

import pytest
from harness import config
from harness.config import load_live_config
from harness.run import Run
from harness.yd import MASK, Result, SecretInOutput, Yd, YdError, mask_variants
from live_samples import (
    AWS,
    PLATFORM,
    SERVICE_ACCOUNT_KEY,
    gcp,
    key_files,
    oci,
    write_config,
)

# Stands in for 'yd': prints what it was given as JSON, or with 'fail <text>'
# prints the text to stderr and exits 1, or with 'exit <n>' exits n
FAKE_YD = """
import hashlib, json, os, sys
args = sys.argv[1:]
if args[0] == "fail":
    print(args[1], file=sys.stderr)
    sys.exit(1)
if args[0] == "exit":
    sys.exit(int(args[1]))
if args[0] == "silent":
    sys.exit(0)
if args[0] == "sleep":
    import time
    time.sleep(10)
print(json.dumps({
    "args": args,
    "cwd": os.getcwd(),
    # The key's hash: the key itself in the output is a SecretInOutput
    "key_sha256": hashlib.sha256(os.environ.get("YD_KEY", "").encode()).hexdigest(),
    "namespace": os.environ.get("YD_NAMESPACE"),
}))
"""


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


@pytest.fixture
def run(tmp_path):
    gcp_key, oci_key = key_files(tmp_path)
    text = (
        PLATFORM
        + AWS
        + gcp(gcp_key)
        + oci(oci_key)
        + '[run]\nprimary_provider = "aws"\n'
    )
    return Run.start(load_live_config(write_config(tmp_path, text)), tmp_path / "runs")


@pytest.fixture
def yd(run):
    return Yd(run, program=(sys.executable, "-c", FAKE_YD))


def test_yd_is_given_the_runs_config_directory_and_environment(yd, run, monkeypatch):
    monkeypatch.setenv("YD_NAMESPACE", "someone-elses")
    seen = yd("list", "keyrings").document
    assert seen["args"] == ["list", "keyrings", "--config", str(run.cli_config)]
    assert seen["cwd"] == str(run.directory.resolve())
    assert seen["key_sha256"] == hashlib.sha256(b"app-key-1234567890").hexdigest()
    assert seen["namespace"] is None


def test_records_are_the_document_as_a_list(yd):
    assert yd("x").records == [yd("x").document]
    assert yd("silent").document is None
    assert yd("silent").records == []


def test_a_failure_raises_unless_allowed(yd):
    with pytest.raises(YdError, match="exited 1"):
        yd("fail", "it broke")
    assert yd("exit", "6", ok=(0, 6)).exit_code == 6
    assert yd("fail", "it broke", check=False).exit_code == 1


def test_a_secret_in_a_failure_is_masked(yd):
    with pytest.raises(YdError) as caught:
        yd("fail", "the secret is dummyDummyDummyDummyDummyDummyDummyDummy")
    message = str(caught.value)
    assert "dummyDummyDummyDummyDummyDummyDummyDummy" not in message
    assert MASK in message


def test_a_pem_line_and_a_json_escaped_key_are_masked(yd):
    with pytest.raises(YdError) as caught:
        yd("fail", "line: MIIEociDummyDummyDummyDummyDummy")
    assert "MIIEociDummyDummyDummyDummyDummy" not in str(caught.value)
    escaped = json.dumps(json.loads(SERVICE_ACCOUNT_KEY)["private_key"])[1:-1]
    with pytest.raises(YdError) as caught:
        yd("fail", f"key: {escaped}")
    assert "MIIEdummyDummyDummyDummyDummy" not in str(caught.value)


def test_a_command_that_runs_too_long_fails(run):
    slow = Yd(run, program=(sys.executable, "-c", FAKE_YD), timeout=1)
    with pytest.raises(YdError, match="still running"):
        slow("sleep")


def test_short_secrets_are_not_masked():
    assert mask_variants(["abc"]) == []


def test_a_service_accounts_private_key_lines_are_masked_but_not_its_email():
    variants = mask_variants([SERVICE_ACCOUNT_KEY])
    assert "MIIEdummyDummyDummyDummyDummy" in variants
    assert "x@yd-dummy.iam.gserviceaccount.com" not in variants


def test_a_results_repr_holds_none_of_its_output():
    """
    A Result's output is unmasked; pytest may show its repr. (Its arguments
    never hold a secret: those reach 'yd' through its environment.)
    """
    secret = "dummyDummyDummyDummyDummyDummyDummyDummy"
    shown = repr(Result(("show", "x"), 1, f"out {secret}", f"err {secret}"))
    assert secret not in shown
    assert "exit_code=1" in shown


SECRET = "dummyDummyDummyDummyDummyDummyDummyDummy"  # [aws] secret_access_key


def test_a_secret_on_stdout_fails_the_call(yd):
    with pytest.raises(SecretInOutput) as raised:
        yd("echo", SECRET, check=False)
    message = str(raised.value)
    assert "[aws] secret_access_key" in message
    assert SECRET not in message


def test_a_secret_on_stderr_fails_the_call(yd):
    with pytest.raises(SecretInOutput):
        yd("fail", f"the secret is {SECRET}", check=False)


def test_a_service_account_key_line_fails_the_call(yd):
    with pytest.raises(SecretInOutput) as raised:
        yd("fail", "line: MIIEdummyDummyDummyDummyDummy", check=False)
    assert "[gcp] service_account_key_file" in str(raised.value)


def test_a_secret_in_output_is_a_yd_error_with_the_output_masked(yd):
    # The existing masking tests rely on this: SecretInOutput is a YdError
    with pytest.raises(YdError) as raised:
        yd("fail", f"the secret is {SECRET}")
    assert MASK in str(raised.value)


def test_clean_output_passes(yd):
    assert yd("echo", "nothing secret").exit_code == 0


def test_the_application_key_is_masked_but_does_not_fail_the_call(yd):
    # yd doctor shows the key ID on purpose; it is masked, not refused
    with pytest.raises(YdError) as raised:
        yd("fail", "key: app-key-1234567890")
    assert not isinstance(raised.value, SecretInOutput)
    assert "app-key-1234567890" not in str(raised.value)
    assert yd("echo", "app-key-1234567890").exit_code == 0
