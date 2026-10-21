"""
One run of the live system tests: its ID, the names of everything it makes,
and the configuration file and environment every 'yd' it runs is given.

The run ID is 'ydst-<yymmddhhmm>-<4 base36>', UTC, so a name says which run
made it and when; the sweep reads both back. The run's tag is its run ID.

Secrets never reach the configuration file: 'yd' gets them as YD_KEY,
YD_SECRET, YD_URL, YD_VAR_<name> and YD_DATA_CLIENT_REMOTE, and the file
defines none of those variables, since a file selected with '-c' outranks the
environment for the variables it defines. Every inherited YD_* variable is
dropped, so a developer's YD_NAMESPACE cannot leak into a run.
"""

from __future__ import annotations

import json
import re
import secrets
import string
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from harness import data
from harness.config import SCHEMA, LiveConfig

RUN_PREFIX = "ydst"
# The namespaces, fixed rather than configured: the Platform never deletes a
# namespace that has been populated, so each name used is permanent (see
# tests/README.md's Namespaces). Runs share NAMESPACE, kept apart by their run
# IDs, as the resource system tests do (tests/resources/test-config.toml); the
# failure tests' limited Application may read LIMITED_NAMESPACE alone, a
# namespace no test puts work in, so its listing there is empty
NAMESPACE = "yd-cli-system-tests"
LIMITED_NAMESPACE = "yd-cli-tests"
SPECS = Path(__file__).resolve().parent.parent / "specs"
INSTALLER = SPECS / "install-agent.sh"  # The Agent installer, user data for every pool
_ALPHABET = string.digits + string.ascii_lowercase
_RUN_ID = re.compile(rf"^({RUN_PREFIX}-(\d{{10}})-[0-9a-z]{{4}})(?:-|$)")


def new_run_id(now: datetime | None = None) -> str:
    """
    A new run ID, stamped with when the run started.
    """
    started = now or datetime.now(timezone.utc)
    suffix = "".join(secrets.choice(_ALPHABET) for _ in range(4))
    return f"{RUN_PREFIX}-{started:%y%m%d%H%M}-{suffix}"


def run_id_of(name: str) -> str | None:
    """
    The run ID a name starts with, or None for a name no run made.
    """
    match = _RUN_ID.match(name)
    return match[1] if match else None


def run_started(run_id: str) -> datetime:
    """
    When a run started, read from its ID; ValueError if it is not one.
    """
    match = _RUN_ID.match(run_id)
    if match is None:
        raise ValueError(f"'{run_id}' is not a run ID")
    return datetime.strptime(match[2], "%y%m%d%H%M").replace(tzinfo=timezone.utc)


@dataclass(frozen=True)
class Run:
    """
    A run: its configuration, its ID, and the directory holding the CLI
    configuration its 'yd' commands are given.
    """

    config: LiveConfig
    run_id: str
    directory: Path

    @classmethod
    def start(cls, config: LiveConfig, parent: Path, run_id: str | None = None) -> Run:
        """
        A new run, its directory under 'parent' and its CLI configuration
        written. Nothing remote is touched.
        """
        run_id = run_id or new_run_id()
        directory = parent / run_id
        directory.mkdir(parents=True)
        run = cls(config, run_id, directory)
        run.cli_config.write_text(run.render_cli_config(), encoding="utf-8")
        return run

    @property
    def namespace(self) -> str:
        return NAMESPACE

    @property
    def tag(self) -> str:
        return self.run_id

    @property
    def cli_config(self) -> Path:
        return self.directory / "config.toml"

    def name(self, *parts: str) -> str:
        """
        A name for something the run makes: the run ID, then the parts.
        """
        return "-".join((self.run_id, *parts))

    @property
    def keyring(self) -> str:
        return self.name("keyring")

    @property
    def allowance_description(self) -> str:
        return self.name("allowance")

    def credential_name(self, provider: str) -> str:
        return self.name(provider)

    def source_template(self, provider: str) -> str:
        return self.name(provider, "ondemand")

    def requirement_template(self, provider: str) -> str:
        return self.name(provider, "static")

    def image_family(self, provider: str) -> str:
        return self.name(provider, "images")

    def pool_name(self, provider: str) -> str:
        return self.name(provider, "pool")

    def worker_tag(self, provider: str) -> str:
        return self.name(provider)

    def standalone_name(self, provider: str) -> str:
        """
        The Compute Requirement, managed by no Worker Pool, that the stop,
        start and restart steps act on.
        """
        return self.name(provider, "standalone")

    def actions_pool_name(self) -> str:
        """
        The primary's actions pool, on which the action scenarios run work.
        """
        return self.name(self.config.primary, "actions", "pool")

    def actions_worker_tag(self) -> str:
        return self.name(self.config.primary, "actions")

    def configured_pool_name(self) -> str:
        return self.name("configured", "pool")

    def actions_standalone_name(self) -> str:
        return self.name(self.config.primary, "actions", "standalone")

    def spec_files(self) -> list[Path]:
        """
        The specifications 'yd resource create' sets the run up from.
        """
        return [
            SPECS / "common.jsonnet",
            *(SPECS / f"{provider}.jsonnet" for provider in self.config.providers),
        ]

    def variables(self) -> dict[str, str]:
        """
        The run's non-secret variables: its names, and every non-secret value
        each provider was configured with, as '<provider>_<key>'. An unset
        optional value is left out, for the specifications' '::' to drop.
        """
        found = {
            "run_id": self.run_id,
            "keyring": self.keyring,
            "allowance_description": self.allowance_description,
            "max_instance_hours": str(self.config.run["max_instance_hours"]),
        }
        for provider, section in self.config.providers.items():
            found[f"{provider}_credential_name"] = self.credential_name(provider)
            found[f"{provider}_credential"] = (
                f"{self.keyring}/{self.credential_name(provider)}"
            )
            found[f"{provider}_source_template"] = self.source_template(provider)
            found[f"{provider}_image_family"] = self.image_family(provider)
            found[f"{provider}_requirement_template"] = self.requirement_template(
                provider
            )
            for key, spec in SCHEMA[provider].items():
                value = section[key]
                if not spec.secret and value is not None:
                    found[f"{provider}_{key}"] = str(value)
        remote = data.task_remote(self.config)
        if remote is not None:
            found["task_data_remote"] = remote
        return found

    def secret_variables(self) -> dict[str, str]:
        """
        The run's secret variables, named 'secret_<provider>_<key>' so that
        'yd variables' redacts every one by its name.
        """
        found: dict[str, str] = {}
        for provider, section in self.config.providers.items():
            for key, spec in SCHEMA[provider].items():
                value = section[key]
                if spec.secret and value is not None:
                    found[f"secret_{provider}_{key}"] = value
        return found

    def render_cli_config(self) -> str:
        """
        The CLI configuration file: the namespace, the tag and the run's
        non-secret variables.
        """
        lines = [
            f"# Generated by the live system tests for run {self.run_id}.",
            "# Secrets are not here: 'yd' gets them as YD_KEY, YD_SECRET and YD_VAR_*.",
            "",
            "[common]",
            f"namespace = {json.dumps(self.namespace)}",
            f"tag = {json.dumps(self.tag)}",
            "",
            "[common.variables]",
            *(
                f"{name} = {json.dumps(value)}"
                for name, value in sorted(self.variables().items())
            ),
        ]
        if self.config.data is not None:
            # No prefix: its default, '{{namespace}}/{{tag}}', is the run's
            # (the tag being the run ID), for the data client commands and a
            # Work Requirement's {{dataClient.prefix}} alike
            bucket = json.dumps(self.config.data["bucket"])
            lines += ["", "[dataClient]", f"bucket = {bucket}"]
        return "\n".join(lines) + "\n"

    def environment(self, inherited: Mapping[str, str]) -> dict[str, str]:
        """
        The environment for a 'yd' subprocess: the inherited one less every
        YD_* and YDST_* variable, then the Platform's credentials and the
        run's secret variables.
        """
        environment = {
            name: value
            for name, value in inherited.items()
            if not name.startswith(("YD_", "YDST_"))
        }
        environment["YD_KEY"] = self.config.platform["key"]
        environment["YD_SECRET"] = self.config.platform["secret"]
        if self.config.platform["url"]:
            environment["YD_URL"] = self.config.platform["url"]
        for name, value in self.secret_variables().items():
            environment[f"YD_VAR_{name}"] = value
        remote = data.local_remote(self.config)
        if remote is not None:
            environment["YD_DATA_CLIENT_REMOTE"] = remote
        return environment
