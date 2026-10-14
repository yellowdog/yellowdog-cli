"""
A run of the live suite: its ID, its names, and what each 'yd' it runs is given.
"""

from datetime import datetime, timedelta, timezone

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

import pytest
from harness import config
from harness.config import load_live_config
from harness.run import SPECS, Run, new_run_id, run_id_of, run_started
from live_samples import AWS, PLATFORM, gcp, oci, write_config

STARTED = datetime(2026, 10, 12, 15, 30, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


@pytest.fixture
def every_provider(tmp_path):
    text = PLATFORM + AWS + gcp() + oci() + '[run]\nprimary_provider = "aws"\n'
    return load_live_config(write_config(tmp_path, text))


def test_a_run_id_carries_when_it_started():
    run_id = new_run_id(STARTED)
    assert run_id.startswith("ydst-2610121530-")
    assert len(run_id) == len("ydst-2610121530-ab12")
    assert run_started(run_id) == STARTED


def test_run_ids_differ():
    assert len({new_run_id(STARTED) for _ in range(50)}) > 45


def test_the_run_id_of_a_name():
    assert run_id_of("ydst-2610121530-ab12-aws-ondemand") == "ydst-2610121530-ab12"
    assert run_id_of("ydst-2610121530-ab12") == "ydst-2610121530-ab12"
    assert run_id_of("ydst-2610121530-ab12x-aws") is None
    assert run_id_of("ydst-notarun-aws") is None
    assert run_id_of("other-2610121530-ab12") is None


def test_run_started_refuses_what_is_not_a_run_id():
    with pytest.raises(ValueError):
        run_started("ydst-2613451530-ab12")  # month 13


def test_names_carry_the_run_id(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs", run_id="ydst-2610121530-ab12")
    assert run.tag == "ydst-2610121530-ab12"
    assert run.keyring == "ydst-2610121530-ab12-keyring"
    assert run.source_template("aws") == "ydst-2610121530-ab12-aws-ondemand"
    assert run.requirement_template("gcp") == "ydst-2610121530-ab12-gcp-static"


def test_a_pool_and_its_worker_tag_are_named_for_the_run(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs", run_id="ydst-2610121530-ab12")
    assert run.pool_name("aws") == "ydst-2610121530-ab12-aws-pool"
    assert run.worker_tag("aws") == "ydst-2610121530-ab12-aws"
    assert run.standalone_name("aws") == "ydst-2610121530-ab12-aws-standalone"


def test_each_providers_image_family_is_named_for_the_run(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs", run_id="ydst-2610121530-ab12")
    assert run.image_family("gcp") == "ydst-2610121530-ab12-gcp-images"
    assert run.variables()["oci_image_family"] == "ydst-2610121530-ab12-oci-images"


def test_the_spec_files_are_the_common_one_then_each_provider(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs")
    assert run.spec_files() == [
        SPECS / "common.jsonnet",
        SPECS / "aws.jsonnet",
        SPECS / "gcp.jsonnet",
        SPECS / "oci.jsonnet",
    ]


def test_the_cli_config_holds_the_namespace_tag_and_variables(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs", run_id="ydst-2610121530-ab12")
    document = tomllib.loads(run.cli_config.read_text(encoding="utf-8"))
    assert document["common"]["namespace"] == "yd-cli-system-tests"
    assert document["common"]["tag"] == "ydst-2610121530-ab12"
    variables = document["common"]["variables"]
    assert variables["aws_region"] == "eu-west-2"
    assert variables["aws_credential"] == (
        "ydst-2610121530-ab12-keyring/ydst-2610121530-ab12-aws"
    )
    assert variables["oci_shape"] == "VM.Standard.E4.Flex"
    assert variables["max_instance_hours"] == "4"
    assert variables["aws_subnet_id"] == "subnet-00000000000000000"
    assert variables["aws_availability_zone"] == "eu-west-2a"
    assert "gcp_zone" not in variables  # Unset: the spec leaves it out


def test_no_secret_is_written_to_the_cli_config(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs")
    text = run.cli_config.read_text(encoding="utf-8")
    for secret in every_provider.secrets():
        for line in secret.splitlines():
            if len(line) > 8:
                assert line not in text
    for name in run.secret_variables():
        assert name not in text


def test_secret_variables_carry_the_inline_keys(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs")
    secrets = run.secret_variables()
    assert secrets["secret_gcp_service_account_key_json"].startswith(
        '{"type": "service_account"'
    )
    assert secrets["secret_oci_private_key"].startswith("-----BEGIN PRIVATE KEY-----")
    assert (
        secrets["secret_aws_secret_access_key"]
        == "dummyDummyDummyDummyDummyDummyDummyDummy"
    )


def test_the_environment_replaces_every_inherited_yd_variable(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs")
    inherited = {
        "PATH": "/usr/bin",
        "YD_NAMESPACE": "someone-elses",
        "YD_TAG": "theirs",
        "YD_VAR_aws_region": "us-east-1",
        "YD_KEY": "their-key",
        "YDST_AWS_REGION": "us-east-1",
    }
    environment = run.environment(inherited)
    assert environment["PATH"] == "/usr/bin"
    assert "YD_NAMESPACE" not in environment
    assert "YD_TAG" not in environment
    assert "YD_VAR_aws_region" not in environment
    assert "YDST_AWS_REGION" not in environment
    assert environment["YD_KEY"] == "app-key-1234567890"
    assert environment["YD_SECRET"] == "app-secret-abcdefghijklmnop"
    assert "YD_URL" not in environment
    assert environment["YD_VAR_secret_aws_secret_access_key"] == (
        "dummyDummyDummyDummyDummyDummyDummyDummy"
    )


def test_a_new_run_gets_a_directory_of_its_own(every_provider, tmp_path):
    first = Run.start(every_provider, tmp_path / "runs")
    second = Run.start(every_provider, tmp_path / "runs")
    assert first.directory != second.directory
    assert first.cli_config.is_file() and second.cli_config.is_file()


def test_an_old_run_is_older_than_a_day():
    run_id = new_run_id(STARTED - timedelta(days=2))
    assert STARTED - run_started(run_id) > timedelta(hours=24)


def test_a_runs_repr_holds_no_secret(every_provider, tmp_path):
    """
    pytest shows a repr in a failed assertion and under '--showlocals'.
    """
    shown = repr(Run.start(every_provider, tmp_path / "runs"))
    for secret in every_provider.secrets():
        for line in secret.splitlines():
            if len(line) > 8:
                assert line not in shown


def test_every_secret_variable_is_one_yd_variables_redacts(every_provider, tmp_path):
    from yellowdog_cli.utils.variable_syntax import SECRET_VARIABLE_NAME_PATTERN

    run = Run.start(every_provider, tmp_path / "runs")
    names = list(run.secret_variables())
    assert names, "the fixture configures secrets"
    for name in names:
        assert SECRET_VARIABLE_NAME_PATTERN.search(name), name


def test_the_actions_pool_is_named_for_the_primary(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs", run_id="ydst-2610121530-ab12")
    assert run.actions_pool_name() == "ydst-2610121530-ab12-aws-actions-pool"
    assert run.actions_worker_tag() == "ydst-2610121530-ab12-aws-actions"


def test_the_configured_pool_and_actions_standalone_are_named(every_provider, tmp_path):
    run = Run.start(every_provider, tmp_path / "runs", run_id="ydst-2610121530-ab12")
    assert run.configured_pool_name() == "ydst-2610121530-ab12-configured-pool"
    assert (
        run.actions_standalone_name() == "ydst-2610121530-ab12-aws-actions-standalone"
    )
