"""
The read timeout each Platform client is built with: the commands' ([common]
readTimeout, the SDK's own 90 seconds when unset, none for 0), yd-doctor's
(its --timeout) and a Tab lookup's (its two seconds).
"""

import dataclasses
from datetime import timedelta
from types import SimpleNamespace

import pytest
from yellowdog_client import PlatformClient

import yellowdog_cli.utils.completion_lookups as completion_lookups
import yellowdog_cli.utils.doctor_checks as doctor_checks
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.lazy import value
from yellowdog_cli.utils.limits import LOOKUP_TIMEOUT_SECONDS, PLATFORM_READ_TIMEOUT


@pytest.fixture
def schemas(monkeypatch) -> list:
    """
    The ServicesSchema each PlatformClient.create() is given; no client is built.
    """
    seen: list = []
    monkeypatch.setattr(
        PlatformClient,
        "create",
        staticmethod(lambda schema, _key: seen.append(schema) or object()),
    )
    return seen


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (PLATFORM_READ_TIMEOUT, timedelta(seconds=PLATFORM_READ_TIMEOUT)),
        (30.0, timedelta(seconds=30)),
        (None, None),  # readTimeout = 0: no limit
    ],
)
def test_the_commands_client_waits_the_configured_read_timeout(
    schemas, monkeypatch, configured, expected
):
    config = dataclasses.replace(
        value(wrapper_module.CONFIG_COMMON), read_timeout=configured
    )
    monkeypatch.setattr(wrapper_module, "CONFIG_COMMON", config)
    wrapper_module._create_client()
    assert schemas[0].readTimeout == expected


def test_the_platform_read_timeout_is_the_sdks_default():
    # The CLI's default, shared by its direct requests; held to the SDK's
    from yellowdog_client.model import ServicesSchema

    assert ServicesSchema.DEFAULT_READ_TIMEOUT == timedelta(
        seconds=PLATFORM_READ_TIMEOUT
    )


def test_doctors_client_waits_its_timeout(schemas):
    config = SimpleNamespace(url="https://x", key="k", secret="s")
    doctor_checks._build_client(config, 7)
    assert schemas[0].readTimeout == timedelta(seconds=7)


def test_a_lookups_client_waits_no_longer_than_a_tab(schemas):
    common = SimpleNamespace(url="https://x", key="k", secret="s")
    completion_lookups._client(common)  # type: ignore[arg-type]
    assert schemas[0].readTimeout == timedelta(seconds=LOOKUP_TIMEOUT_SECONDS)
