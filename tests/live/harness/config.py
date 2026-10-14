"""
The live system tests' configuration: a TOML file, with an environment
override for every key, validated once before anything remote is touched.

The file is YDST_CONFIG, else ~/.config/yellowdog/system-tests.toml: outside
the repository, so that the secrets it holds cannot be committed. Every key
can be set or overridden as YDST_<SECTION>_<KEY> (YDST_AWS_SECRET_ACCESS_KEY),
so a CI job can supply everything with no file at all; an empty value counts
as unset. The Platform's key, secret and URL fall back to YD_KEY, YD_SECRET
and YD_URL, which the other live suites use, unless DUMMY_CREDENTIALS_MARKER
says those are the dummies the root conftest.py supplies where the CLI has
no configuration of its own.

A provider with no section is skipped; one with a section is to be tested,
so an incomplete one is an error. Every problem is reported at once.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_ENV = "YDST_CONFIG"
DEFAULT_PATH = Path("~/.config/yellowdog/system-tests.toml")
OVERRIDE_PREFIX = "YDST_"
PROVIDERS = ("aws", "azure", "gcp", "oci")
PLATFORM_FALLBACKS = {"key": "YD_KEY", "secret": "YD_SECRET", "url": "YD_URL"}
# Set by the root conftest.py beside the dummy YD_KEY and YD_SECRET it supplies
DUMMY_CREDENTIALS_MARKER = "YD_TEST_DUMMY_CREDENTIALS"


@dataclass(frozen=True)
class Key:
    """
    One configuration key: its type, and whether it is required, a secret,
    a JSON object or a PEM private key. A 'shown' secret is one
    the CLI prints on purpose (the Application key ID, in 'yd doctor'): it
    is masked in what the harness shows, but printing it does not fail a
    call.
    """

    kind: type
    required: bool = False
    secret: bool = False
    json: bool = False
    pem: bool = False
    default: Any = None
    shown: bool = False


SCHEMA: dict[str, dict[str, Key]] = {
    "platform": {
        "url": Key(str),
        "key": Key(str, required=True, secret=True, shown=True),
        "secret": Key(str, required=True, secret=True),
    },
    "run": {
        "primary_provider": Key(str),
        "namespace": Key(str, default="yd-cli-system-tests"),
        "max_instances_per_provider": Key(int, default=2),
        "max_instance_hours": Key(int, default=4),
        "provision_timeout_minutes": Key(int, default=15),
        "teardown_timeout_minutes": Key(int, default=15),
        "sweep_age_hours": Key(int, default=24),
        "sweep_on_start": Key(bool, default=True),
        "keep_on_failure": Key(bool, default=False),
        "terminate_on_keep": Key(bool, default=True),
    },
    "aws": {
        "access_key_id": Key(str, required=True, secret=True),
        "secret_access_key": Key(str, required=True, secret=True),
        "region": Key(str, required=True),
        "security_group_id": Key(str, required=True),
        "subnet_id": Key(str, required=True),
        "availability_zone": Key(str, required=True),  # The subnet's
        "instance_type": Key(str, default="t3a.small"),
        "image_id": Key(str, required=True),
        "iam_instance_profile_arn": Key(str),  # For the instances' own S3 access
    },
    "azure": {
        "tenant_id": Key(str, required=True),
        "client_id": Key(str, required=True),
        "key": Key(str, required=True, secret=True),  # The client secret
        "subscription_id": Key(str, required=True),
        "region": Key(str, required=True),
        "network_resource_group_name": Key(str, required=True),
        "network_name": Key(str, required=True),
        "subnet_name": Key(str, required=True),
        "vm_size": Key(str, default="Standard_B2s"),
        "image_id": Key(str, required=True),
        "ssh_public_key": Key(str),
    },
    "gcp": {
        # The key file's contents
        "service_account_key_json": Key(str, required=True, secret=True, json=True),
        "project": Key(str, required=True),
        "region": Key(str, required=True),
        "zone": Key(str),
        "network": Key(str),
        "subnetwork": Key(str),
        "machine_type": Key(str, default="e2-small"),
        "image": Key(
            str,
            default="projects/ubuntu-os-cloud/global/images/family/ubuntu-2404-lts-amd64",
        ),
    },
    "oci": {
        "tenant_id": Key(str, required=True),
        "user_id": Key(str, required=True),
        "fingerprint": Key(str, required=True),
        "private_key": Key(str, required=True, secret=True, pem=True),
        "passphrase": Key(str, secret=True),  # The private key's, if encrypted
        "region": Key(str, required=True),
        "compartment_id": Key(str, required=True),
        "subnet_id": Key(str, required=True),
        "shape": Key(str, required=True),
        "image_id": Key(str, required=True),
    },
    "data": {
        # The remotes are built from [aws] (harness/data.py)
        "bucket": Key(str, required=True),
    },
}

_KIND_NAMES = {
    str: "a string",
    int: "an integer",
    bool: "true or false",
}
_TRUE = {"true", "yes", "on", "1"}
_FALSE = {"false", "no", "off", "0"}


@dataclass(frozen=True)
class Section:
    """
    One section's values: every key of its schema, its default or None where
    neither the file nor the environment gave one. The values are left out of its repr, which pytest shows in a failure.
    """

    name: str
    values: Mapping[str, Any] = field(repr=False)

    def __getitem__(self, key: str) -> Any:
        return self.values[key]

    def labelled_secrets(self, *, shown: bool = True) -> dict[str, str]:
        """
        The section's secret values by '[<section>] <key>'; without 'shown',
        leaving out those the CLI shows.
        """
        found: dict[str, str] = {}
        for key, spec in SCHEMA[self.name].items():
            value = self.values[key]
            if spec.secret and value is not None and (shown or not spec.shown):
                found[f"[{self.name}] {key}"] = value
        return found

    def secrets(self) -> list[str]:
        """
        The section's secret values.
        """
        return list(self.labelled_secrets().values())


@dataclass(frozen=True)
class LiveConfig:
    """
    The validated configuration: the Platform, the run's settings, every
    enabled provider (in PROVIDERS order), the primary, and [data] if given.
    """

    path: Path | None
    platform: Section
    run: Section
    providers: Mapping[str, Section]
    primary: str
    data: Section | None

    def labelled_secrets(self, *, shown: bool = True) -> dict[str, str]:
        """
        Every configured secret by where it was configured, the data remote
        built from [aws] among them; without 'shown', leaving out those the
        CLI shows on purpose, which are masked but may be printed.
        """
        from harness import data  # data imports this module

        found: dict[str, str] = {}
        for section in (self.platform, *self.providers.values()):
            found.update(section.labelled_secrets(shown=shown))
        remote = data.local_remote(self)
        if remote is not None:
            found[data.DATA_LABEL] = remote
        return found

    def secrets(self) -> list[str]:
        """
        Every configured secret, for masking.
        """
        return list(self.labelled_secrets().values())

    def summary(self) -> str:
        """
        One line for the session header: where the configuration came from,
        the providers enabled, the primary, and those skipped.
        """
        skipped = [provider for provider in PROVIDERS if provider not in self.providers]
        return (
            f"live config: {self.path or 'environment only'};"
            f" providers: {', '.join(self.providers)} (primary {self.primary});"
            f" skipped: {', '.join(skipped) or 'none'}"
        )


class LiveConfigError(Exception):
    """
    Every problem found with the configuration, reported together.
    """

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__(
            "The live system tests' configuration has problems:\n"
            + "\n".join(f"  - {problem}" for problem in self.problems)
        )


def load_live_config(environ: Mapping[str, str] | None = None) -> LiveConfig:
    """
    Load and validate the configuration from the file and the environment
    ('environ', os.environ by default); raises LiveConfigError.
    """
    environ = os.environ if environ is None else environ
    problems: list[str] = []
    path, document = _read_document(environ, problems)
    _apply_environment(document, environ, problems)

    sections: dict[str, Section] = {}
    for name, raw in document.items():
        if name not in SCHEMA:
            problems.append(f"unknown section [{name}]")
        elif not isinstance(raw, dict):
            problems.append(f"[{name}] must be a table")
        else:
            sections[name] = _section(name, raw, problems)

    platform = sections.get("platform") or _section("platform", {}, problems)
    run = sections.get("run") or _section("run", {}, problems)
    providers = {name: sections[name] for name in PROVIDERS if name in sections}
    primary = _primary(run, providers, problems)
    if problems:
        raise LiveConfigError(problems)
    return LiveConfig(
        path=path,
        platform=platform,
        run=run,
        providers=MappingProxyType(providers),
        primary=primary,
        data=sections.get("data"),
    )


def _read_document(
    environ: Mapping[str, str], problems: list[str]
) -> tuple[Path | None, dict]:
    """
    The file's contents, or nothing when there is no file: a missing default
    file means the environment configures everything, a missing named one
    is an error.
    """
    named = environ.get(CONFIG_ENV)
    path = Path(named or DEFAULT_PATH).expanduser()
    if not path.is_file():
        if named:
            problems.append(f"{CONFIG_ENV} names '{path}', which is not a file")
        return None, {}
    try:
        with path.open("rb") as file:
            return path, tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as error:
        problems.append(f"cannot read '{path}': {error}")
        return path, {}


def _apply_environment(
    document: dict, environ: Mapping[str, str], problems: list[str]
) -> None:
    """
    Fill the Platform's key, secret and URL from YD_* where the file gives
    none (never from the test run's dummies), then apply every
    YDST_<SECTION>_<KEY> override.
    """
    dummies = bool(environ.get(DUMMY_CREDENTIALS_MARKER))
    for key, variable in PLATFORM_FALLBACKS.items():
        if dummies and key != "url":
            continue
        if environ.get(variable):
            section = document.setdefault("platform", {})
            if isinstance(section, dict):
                section.setdefault(key, environ[variable])

    for variable in sorted(environ):
        if not variable.startswith(OVERRIDE_PREFIX) or variable == CONFIG_ENV:
            continue
        name, _, key = variable[len(OVERRIDE_PREFIX) :].lower().partition("_")
        spec = SCHEMA.get(name, {}).get(key)
        if spec is None:
            problems.append(f"{variable} names no configuration key")
            continue
        try:
            value = _from_text(environ[variable], spec.kind)
        except ValueError:
            problems.append(f"{variable} must be {_KIND_NAMES[spec.kind]}")
            continue
        section = document.setdefault(name, {})
        if isinstance(section, dict):
            section[key] = value


def _from_text(text: str, kind: type) -> Any:
    """
    An environment value as the key's type; raises ValueError. Empty text
    stays empty, so that it counts as unset.
    """
    if text == "" or kind is str:
        return text
    if kind is bool:
        lowered = text.strip().lower()
        if lowered in _TRUE:
            return True
        if lowered in _FALSE:
            return False
        raise ValueError(text)
    return kind(text)


def _is_kind(value: Any, kind: type) -> bool:
    """
    Whether a TOML value is of the key's type; a bool is never a number.
    """
    if isinstance(value, bool):
        return kind is bool
    return isinstance(value, kind)


def _section(name: str, raw: dict, problems: list[str]) -> Section:
    """
    One section, checked against its schema: unknown keys, types, required
    keys, inline JSON and PEM private keys.
    """
    schema = SCHEMA[name]
    values: dict[str, Any] = {}
    for key, value in raw.items():
        spec = schema.get(key)
        if spec is None:
            problems.append(f"[{name}] has no key '{key}'")
        elif value == "":
            continue  # Unset
        elif not _is_kind(value, spec.kind):
            problems.append(f"[{name}] {key} must be {_KIND_NAMES[spec.kind]}")
        else:
            values[key] = value

    for key, spec in schema.items():
        if key not in values:
            if spec.required:
                problems.append(f"[{name}] needs {key}")
            values[key] = spec.default
        elif spec.json and not _is_json_object(values[key]):
            problems.append(f"[{name}] {key} is not a JSON object")
        elif spec.pem and not _is_pem_private_key(values[key]):
            problems.append(f"[{name}] {key} is not a PEM private key")
    return Section(name, MappingProxyType(values))


def _is_json_object(text: str) -> bool:
    """
    Whether the text is a JSON object, allowing newlines and other control
    characters inside its strings, as the Platform does.
    """
    try:
        return isinstance(json.loads(text, strict=False), dict)
    except ValueError:
        return False


def _is_pem_private_key(text: str) -> bool:
    """
    Whether the text is a PEM private key: its BEGIN line, then its END line.
    """
    begin = text.find("-----BEGIN ")
    end = text.find("-----END ")
    return 0 <= begin < end and "PRIVATE KEY-----" in text[begin:end]


def _primary(
    run: Section, providers: Mapping[str, Section], problems: list[str]
) -> str:
    """
    The primary provider: the one named, or the only one configured.
    """
    primary = run["primary_provider"]
    if not providers:
        problems.append(
            "no provider is configured: give at least one of "
            + ", ".join(f"[{provider}]" for provider in PROVIDERS)
        )
        return ""
    if primary is None:
        if len(providers) == 1:
            return next(iter(providers))
        problems.append(
            "[run] primary_provider is needed when more than one provider is configured"
        )
        return ""
    if primary not in providers:
        problems.append(
            f"[run] primary_provider '{primary}' is not a configured provider"
            f" ({', '.join(providers)})"
        )
        return ""
    return primary
