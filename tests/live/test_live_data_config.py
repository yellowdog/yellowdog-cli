"""
The data configuration: [data] is a bucket, and both remotes are built from
[aws]: the local one with its keys (a secret), the Task one keyless.
"""

import pytest
from harness import config as config_module
from harness import data
from harness.config import LiveConfigError, load_live_config
from harness.run import Run
from live_samples import AWS, DATA, PLATFORM, PROFILE, write_config


@pytest.fixture(autouse=True)
def _no_default_file(monkeypatch, tmp_path):
    monkeypatch.setattr(config_module, "DEFAULT_PATH", tmp_path / "absent.toml")


def _config(tmp_path, text: str):
    return load_live_config(write_config(tmp_path, text))


def test_data_is_a_bucket_alone(tmp_path):
    with pytest.raises(LiveConfigError, match=r"\[data\] has no key 'remote'"):
        _config(tmp_path, PLATFORM + AWS + DATA + 'remote = "x"\n')


def test_the_local_remote_carries_the_aws_keys_and_region(tmp_path):
    remote = data.local_remote(_config(tmp_path, PLATFORM + AWS + DATA))
    assert remote.startswith(":s3,provider=AWS,env_auth=false,region=eu-west-2,")
    assert "access_key_id=AKIADUMMYDUMMYDUMMY" in remote
    assert "secret_access_key=dummyDummyDummyDummyDummyDummyDummyDummy" in remote


def test_the_task_remote_carries_no_keys(tmp_path):
    remote = data.task_remote(_config(tmp_path, PLATFORM + AWS + DATA))
    assert remote == ":s3,provider=AWS,env_auth=true,region=eu-west-2"


def test_no_remotes_without_data(tmp_path):
    config = _config(tmp_path, PLATFORM + AWS)
    assert data.local_remote(config) is None and data.task_remote(config) is None
    assert data.unavailable(config) == "no [data] section"


def test_the_scenarios_need_an_instance_profile(tmp_path):
    reason = data.unavailable(_config(tmp_path, PLATFORM + AWS + DATA))
    assert "iam_instance_profile_arn" in reason


def test_the_scenarios_can_run_with_a_bucket_and_a_profile(tmp_path):
    # AWS ends inside the [aws] table, so the profile line joins it
    assert data.unavailable(_config(tmp_path, PLATFORM + AWS + PROFILE + DATA)) is None


def test_the_local_remote_is_a_labelled_secret(tmp_path):
    config = _config(tmp_path, PLATFORM + AWS + DATA)
    labelled = config.labelled_secrets()
    assert labelled[data.DATA_LABEL] == data.local_remote(config)
    assert (
        labelled["[aws] secret_access_key"]
        == "dummyDummyDummyDummyDummyDummyDummyDummy"
    )
    assert data.local_remote(config) in config.secrets()


def test_the_run_gives_yd_the_bucket_the_task_remote_and_the_local_remote(tmp_path):
    config = _config(tmp_path, PLATFORM + AWS + PROFILE + DATA)
    run = Run.start(config, tmp_path / "runs")
    text = run.cli_config.read_text(encoding="utf-8")
    assert '[dataClient]\nbucket = "yd-dummy-bucket"' in text
    # The prefix is the default, the run's '{{namespace}}/{{tag}}'
    assert "prefix" not in text
    assert "secret_access_key" not in text
    assert run.variables()["task_data_remote"] == data.task_remote(config)
    assert run.environment({})["YD_DATA_CLIENT_REMOTE"] == data.local_remote(config)
