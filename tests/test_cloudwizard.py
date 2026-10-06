"""
yd-cloudwizard (cloudwizard.py, utils/cloudwizard_*.py) without a cloud
account: what the command line is refused for, as it is parsed; the Keyring
password printed however setup ends, and under '--quiet'; and a run that
reported an error exiting 1, while carrying on past it.
"""

from argparse import ArgumentParser, Namespace
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils.command_registry import (
    check_cloudwizard_args,
    cloud_provider_of,
)


def _args(**values) -> Namespace:
    defaults = dict(
        cloud_provider="aws", credentials_file=None, operation="setup", region_name=None
    )
    return Namespace(**{**defaults, **values})


class TestTheCommandLine:
    @pytest.mark.parametrize(
        "spelling, provider",
        [("aws", "AWS"), ("Amazon", "AWS"), ("gce", "GCP"), ("AZURE", "Azure")],
    )
    def test_the_provider_spellings(self, spelling, provider):
        assert cloud_provider_of(spelling) == provider

    @pytest.mark.parametrize(
        "values, message",
        [
            ({"cloud_provider": "nimbus"}, "unknown or unsupported cloud provider"),
            ({"cloud_provider": "oci"}, "unknown or unsupported cloud provider"),
            ({"cloud_provider": "gcp"}, "--credentials-file is required for GCP"),
            (
                {
                    "cloud_provider": "gcp",
                    "credentials_file": "c.json",
                    "operation": "add-ssh",
                },
                "'add-ssh' is not supported for GCP",
            ),
            (
                {"cloud_provider": "azure", "operation": "remove-ssh"},
                "'remove-ssh' needs --region-name for Azure",
            ),
        ],
    )
    def test_refused_with_a_usage_error(self, values, message, capsys):
        with pytest.raises(SystemExit) as raised:
            check_cloudwizard_args(
                _args(**values), ArgumentParser(prog="yd-cloudwizard")
            )
        assert raised.value.code == 2
        assert message in capsys.readouterr().err

    @pytest.mark.parametrize(
        "values",
        [
            {},
            {"cloud_provider": "gcp", "credentials_file": "c.json"},
            {
                "cloud_provider": "azure",
                "operation": "add-ssh",
                "region_name": "uksouth",
            },
            {"cloud_provider": "aws", "operation": "add-ssh"},
        ],
    )
    def test_accepted(self, values):
        check_cloudwizard_args(_args(**values), ArgumentParser(prog="yd-cloudwizard"))


# --- the run, with a stand-in provider configuration --------------------------

pytest.importorskip("boto3")  # The cloudwizard extra, which the modules below need

from yellowdog_cli import cloudwizard  # noqa: E402
from yellowdog_cli.utils import cloudwizard_common, printing  # noqa: E402


class _Config(cloudwizard_common.CommonCloudConfig):
    """A provider whose setup creates a Keyring, then fails as told."""

    def __init__(self, fail_with: Exception | None = None, report_error: bool = False):
        super().__init__(ctx=SimpleNamespace(client=None), cloud_provider="Test")  # type: ignore[arg-type]
        self._fail_with = fail_with
        self._report_error = report_error

    def setup(self):
        self._keyring_name, self._keyring_password = "kr", "s3cret"
        if self._report_error:
            cloudwizard_common.print_error("a step failed")
        if self._fail_with is not None:
            raise self._fail_with

    def teardown(self):
        if self._report_error:
            cloudwizard_common.print_error("a step failed")


@pytest.fixture
def printed(monkeypatch):
    lines: list[str] = []
    monkeypatch.setattr(cloudwizard_common, "_ERRORS_REPORTED", 0)
    monkeypatch.setattr(
        printing,
        "ARGS_PARSER",
        SimpleNamespace(
            quiet=True,
            json_output=False,
            count_only=False,
            no_format=True,
            print_pid=False,
        ),
    )
    monkeypatch.setattr(
        cloudwizard_common,
        "print_info",
        lambda m, **k: lines.append(m) if k.get("override_quiet") else None,
    )
    monkeypatch.setattr(printing, "print_error", lambda m: lines.append(f"ERROR {m}"))
    monkeypatch.setattr(
        cloudwizard, "print_error", lambda m: lines.append(f"ERROR {m}")
    )
    return lines


def test_the_keyring_password_is_shown_when_setup_fails(printed):
    with pytest.raises(RuntimeError):
        cloudwizard.run_operation(
            _Config(fail_with=RuntimeError("boom")), "setup", None
        )
    assert any("s3cret" in line for line in printed)


def test_the_keyring_password_is_shown_under_quiet(printed):
    cloudwizard.run_operation(_Config(), "setup", None)
    assert any("s3cret" in line for line in printed)


@pytest.mark.parametrize("operation", ["setup", "teardown"])
def test_a_reported_error_exits_1_after_the_run(printed, operation):
    with pytest.raises(SystemExit) as raised:
        cloudwizard.run_operation(_Config(report_error=True), operation, None)
    assert raised.value.code == 1
    assert "ERROR Cloud Wizard finished with 1 error(s)" in printed


def test_a_clean_run_exits_normally(printed):
    cloudwizard.run_operation(_Config(), "teardown", None)
    assert not any(line.startswith("ERROR") for line in printed)


# --- AWS: error codes, and the SSH confirmation ---------------------------------


def test_an_aws_error_is_told_by_its_code():
    from botocore.exceptions import ClientError

    from yellowdog_cli.utils.cloudwizard_aws import _error_code

    error = ClientError(
        {"Error": {"Code": "NoSuchEntity", "Message": "EntityAlreadyExists in text"}},
        "GetUser",
    )
    assert _error_code(error) == "NoSuchEntity"


def test_add_ssh_in_every_region_is_confirmed_first(monkeypatch):
    from yellowdog_cli.utils import cloudwizard_aws

    asked: list[str] = []
    monkeypatch.setattr(cloudwizard_aws, "_get_opted_in_regions", lambda: ["a", "b"])
    monkeypatch.setattr(
        cloudwizard_aws, "confirmed", lambda question: asked.append(question) or False
    )
    monkeypatch.setattr(
        cloudwizard_aws.boto3,
        "client",
        lambda *a, **k: pytest.fail("no security group may be touched when declined"),
    )
    config = object.__new__(cloudwizard_aws.AWSConfig)
    config.set_ssh_ingress_rule("add-ssh")
    assert asked and "all 2 opted-in regions" in asked[0]
    assert "0.0.0.0/0" in asked[0]
