"""
The live suite's configuration: loading, environment overrides, validation.
"""

import pytest
from harness import config
from harness.config import LiveConfigError, load_live_config
from live_samples import AWS, AZURE, PLATFORM, gcp, key_files, oci, write_config


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    """
    Never read the developer's real ~/.config/yellowdog/system-tests.toml.
    """
    monkeypatch.setattr(config, "DEFAULT_PATH", tmp_path / "absent.toml")


def _problems(environ: dict[str, str]) -> list[str]:
    with pytest.raises(LiveConfigError) as caught:
        load_live_config(environ)
    return caught.value.problems


def test_a_minimal_aws_configuration_loads_with_its_defaults(tmp_path):
    loaded = load_live_config(write_config(tmp_path, PLATFORM + AWS))
    assert list(loaded.providers) == ["aws"]
    assert loaded.primary == "aws"
    assert loaded.run["namespace"] == "yd-cli-system-tests"
    assert loaded.run["max_instance_hours"] == 4
    assert loaded.providers["aws"]["instance_type"] == "t3a.small"
    assert loaded.providers["aws"]["subnet_id"] == "subnet-00000000000000000"
    assert loaded.data is None


def test_aws_needs_a_subnet(tmp_path):
    text = PLATFORM + AWS.replace('subnet_id = "subnet-00000000000000000"\n', "")
    assert _problems(write_config(tmp_path, text)) == ["[aws] needs subnet_id"]


def test_aws_needs_the_subnets_zone(tmp_path):
    text = PLATFORM + AWS.replace('availability_zone = "eu-west-2a"\n', "")
    assert _problems(write_config(tmp_path, text)) == ["[aws] needs availability_zone"]


def test_a_provider_without_a_section_is_skipped(tmp_path):
    loaded = load_live_config(write_config(tmp_path, PLATFORM + AWS))
    assert "azure" not in loaded.providers
    assert "skipped: azure, gcp, oci" in loaded.summary()


def test_a_provider_section_present_but_incomplete_is_an_error(tmp_path):
    problems = _problems(
        write_config(tmp_path, PLATFORM + AWS + '[azure]\nregion = "uksouth"\n')
    )
    assert "[azure] needs tenant_id" in problems
    assert "[azure] needs client_secret" in problems


def test_an_unknown_section_or_key_is_an_error(tmp_path):
    text = PLATFORM + AWS.replace("secret_access_key", "secret_acess_key") + "[azur]\n"
    problems = _problems(write_config(tmp_path, text))
    assert "[aws] has no key 'secret_acess_key'" in problems
    assert "unknown section [azur]" in problems


def test_an_override_replaces_the_file_value(tmp_path):
    environ = write_config(tmp_path, PLATFORM + AWS)
    environ["YDST_AWS_REGION"] = "us-east-1"
    assert load_live_config(environ).providers["aws"]["region"] == "us-east-1"


def test_the_environment_alone_can_configure_everything():
    environ = {
        "YDST_PLATFORM_KEY": "k" * 10,
        "YDST_PLATFORM_SECRET": "s" * 10,
        "YDST_AWS_ACCESS_KEY_ID": "AKIADUMMY",
        "YDST_AWS_SECRET_ACCESS_KEY": "dummy-secret",
        "YDST_AWS_REGION": "eu-west-2",
        "YDST_AWS_SECURITY_GROUP_ID": "sg-0",
        "YDST_AWS_SUBNET_ID": "subnet-0",
        "YDST_AWS_AVAILABILITY_ZONE": "eu-west-2a",
        "YDST_AWS_IMAGE_ID": "ami-0",
    }
    loaded = load_live_config(environ)
    assert loaded.path is None
    assert loaded.primary == "aws"


def test_an_override_naming_no_key_is_an_error(tmp_path):
    environ = write_config(tmp_path, PLATFORM + AWS)
    environ["YDST_AWS_SECRET_ACESS_KEY"] = "x"
    assert "YDST_AWS_SECRET_ACESS_KEY names no configuration key" in _problems(environ)


def test_an_override_is_converted_to_the_keys_type(tmp_path):
    environ = write_config(tmp_path, PLATFORM + AWS)
    environ["YDST_RUN_SWEEP_ON_START"] = "no"
    environ["YDST_RUN_SWEEP_AGE_HOURS"] = "6"
    loaded = load_live_config(environ)
    assert loaded.run["sweep_on_start"] is False
    assert loaded.run["sweep_age_hours"] == 6


def test_an_override_of_the_wrong_type_is_an_error(tmp_path):
    environ = write_config(tmp_path, PLATFORM + AWS)
    environ["YDST_RUN_SWEEP_AGE_HOURS"] = "a day"
    assert "YDST_RUN_SWEEP_AGE_HOURS must be an integer" in _problems(environ)


def test_a_file_value_of_the_wrong_type_is_an_error(tmp_path):
    text = PLATFORM + AWS + "[run]\nsweep_age_hours = true\n"
    assert "[run] sweep_age_hours must be an integer" in _problems(
        write_config(tmp_path, text)
    )


def test_an_empty_value_counts_as_unset(tmp_path):
    environ = write_config(tmp_path, PLATFORM + AWS)
    environ["YDST_AWS_INSTANCE_TYPE"] = ""
    assert load_live_config(environ).providers["aws"]["instance_type"] == "t3a.small"
    environ["YDST_AWS_REGION"] = ""
    assert _problems(environ) == ["[aws] needs region"]


def test_the_platform_falls_back_to_yd_key_secret_and_url(tmp_path):
    environ = write_config(tmp_path, AWS)
    environ.update(YD_KEY="env-key-123", YD_SECRET="env-secret-456", YD_URL="https://x")
    loaded = load_live_config(environ)
    assert loaded.platform["key"] == "env-key-123"
    assert loaded.platform["url"] == "https://x"


def test_the_file_outranks_yd_key_and_ydst_outranks_the_file(tmp_path):
    environ = write_config(tmp_path, PLATFORM + AWS)
    environ["YD_KEY"] = "env-key-123"
    assert load_live_config(environ).platform["key"] == "app-key-1234567890"
    environ["YDST_PLATFORM_KEY"] = "ydst-key-789"
    assert load_live_config(environ).platform["key"] == "ydst-key-789"


def test_two_providers_need_a_primary(tmp_path):
    problems = _problems(write_config(tmp_path, PLATFORM + AWS + AZURE))
    assert (
        "[run] primary_provider is needed when more than one provider is configured"
        in problems
    )


def test_the_primary_must_be_configured(tmp_path):
    text = PLATFORM + AWS + '[run]\nprimary_provider = "gcp"\n'
    problems = _problems(write_config(tmp_path, text))
    assert "[run] primary_provider 'gcp' is not a configured provider (aws)" in problems


def test_no_provider_is_an_error(tmp_path):
    problems = _problems(write_config(tmp_path, PLATFORM))
    assert problems[0].startswith("no provider is configured")


def test_a_key_file_must_exist(tmp_path):
    problems = _problems(write_config(tmp_path, PLATFORM + gcp(tmp_path / "none.json")))
    assert any(
        "service_account_key_file" in p and "not a readable file" in p for p in problems
    )


def test_the_secrets_include_key_file_contents(tmp_path):
    gcp_key, oci_key = key_files(tmp_path)
    text = PLATFORM + gcp(gcp_key) + oci(oci_key) + '[run]\nprimary_provider = "gcp"\n'
    secrets = load_live_config(write_config(tmp_path, text)).secrets()
    assert gcp_key.read_text(encoding="utf-8") in secrets
    assert oci_key.read_text(encoding="utf-8") in secrets
    assert "app-secret-abcdefghijklmnop" in secrets
    assert "ocid1.tenancy.oc1..dummy" not in secrets


def test_every_problem_is_reported_at_once(tmp_path):
    text = '[aws]\nregion = "x"\n[nonsense]\n'
    problems = _problems(write_config(tmp_path, text))
    assert len(problems) >= 5  # key, secret, three AWS keys, the section


def test_a_named_file_that_does_not_exist_is_an_error(tmp_path):
    problems = _problems({"YDST_CONFIG": str(tmp_path / "missing.toml")})
    assert problems[0].startswith("YDST_CONFIG names")


def test_the_test_runs_dummy_credentials_are_never_the_platforms(tmp_path):
    """
    The root conftest sets a dummy YD_KEY and YD_SECRET where the CLI has no
    configuration, and marks them so; the live suite must not take them.
    """
    environ = write_config(tmp_path, AWS)
    environ.update(
        YD_KEY="dummy-key-for-tests",
        YD_SECRET="dummy-secret-for-tests",
        YD_TEST_DUMMY_CREDENTIALS="1",
    )
    problems = _problems(environ)
    assert "[platform] needs key" in problems
    assert "[platform] needs secret" in problems
