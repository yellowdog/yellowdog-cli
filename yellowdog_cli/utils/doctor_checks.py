"""
yd-doctor's checks: the model, the runner, and one function per check.
Nothing here prints; doctor.py renders. Modules that exit at import on a
broken configuration (load_config and dataclient_utils) are imported inside
the checks that need them, never at module level. wrapper is never imported
at all, since importing it builds CLIENT from a strict load: the doctor
builds its own PlatformClient (_build_client()). Nor is the SDK imported at
module level, directly or through entity_utils: an SDK that will not
import is a diagnosis (the 'SDK imports' row), not a crash before the first
row is printed.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

import requests
from pypac import pac_context_for_url

from yellowdog_cli._version import __version__ as CLI_VERSION
from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.check_imports import (
    EXTRA_PROBES,
    check_cloudwizard_imports,
    check_commander_imports,
    check_jsonnet_import,
    check_mcp_imports,
)
from yellowdog_cli.utils.exit_codes import classify
from yellowdog_cli.utils.property_names import (
    DATA_CLIENT_BUCKET,
    DATA_CLIENT_PREFIX,
    DATA_CLIENT_REMOTE,
    KEY,
    NAME_TAG,
    NAMESPACE,
    SECRET,
    URL,
)
from yellowdog_cli.utils.rclone_utils import shown_remote
from yellowdog_cli.utils.rclone_version import find_rclone, rclone_version
from yellowdog_cli.utils.settings import (
    ERROR_MARKER,
    PYPI_PROJECT_URL,
    PYTHON_MAX_TESTED_VERSION,
    PYTHON_MIN_VERSION,
    YD_DATA_CLIENT,
    ExitCode,
)
from yellowdog_cli.utils.version_info import sdk_version


class Status(Enum):
    OK = "OK"
    WARN = "WARN"
    FAIL = "FAIL"
    SKIP = "SKIP"


class Need(Enum):
    NOTHING = auto()
    CONFIG = auto()  # the configuration loaded
    CREDENTIALS = auto()  # key and secret resolved
    NETWORK = auto()  # not --offline
    CONFIG_AND_NETWORK = auto()  # the configuration loaded, and not --offline
    CREDENTIALS_AND_NETWORK = auto()
    DATA_CLIENT = auto()  # a data client remote configured, and not --offline


@dataclass(frozen=True)
class Result:
    status: Status
    detail: str
    remedy: str | None = None


@dataclass(frozen=True)
class Check:
    name: str
    group: str  # "Installation" | "Configuration" | "Platform" | "Data client"
    needs: Need
    run: Callable[[Context], Result]


@dataclass
class Context:
    offline: bool
    timeout: int
    debug: bool = False
    sdk_error: str | None = None  # why the SDK did not import, once checked
    config_loaded: bool = False
    config_error: str | None = None  # the captured text when loading failed
    config_common: Any = None  # ConfigCommon, possibly partial, once loaded
    platform_reachable: bool | None = None  # set by Reachable; None if it did not run
    client: Any = None  # PlatformClient, built by the Authenticated check
    application: Any = None  # ApplicationDetails, recorded by the same check
    # The data client a data client command would use: the profile
    # YD_DATA_CLIENT names, else the [dataClient] base, else the environment
    data_client: Any = None  # ConfigDataClient, None if it did not load
    data_client_name: str | None = None  # its profile's name, for the rows
    data_client_error: str | None = None  # what stopped it loading
    profiles: dict[str, Any] = field(default_factory=dict)  # name -> ConfigDataClient
    profile_errors: dict[str, str] = field(default_factory=dict)  # why one did not load


def with_timeout(fn: Callable[[], Any], seconds: float) -> Any:
    """
    Run fn on a daemon thread and wait 'seconds' for it. Returns fn's value,
    or a FAIL Result naming the timeout; re-raises fn's exception. The SDK's
    own HTTP calls carry no timeout, so this is the only budget they have.
    """
    box: dict[str, Any] = {}

    def target() -> None:
        try:
            box["value"] = fn()
        except BaseException as e:  # handed back to the caller
            box["error"] = e

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(seconds)
    if thread.is_alive():
        return Result(
            Status.FAIL,
            f"no answer within {seconds} seconds",
            "Check the URL, proxy and network, or raise --timeout",
        )
    if "error" in box:
        raise box["error"]
    return box["value"]


_NETWORK_NEEDS = (
    Need.NETWORK,
    Need.CONFIG_AND_NETWORK,
    Need.CREDENTIALS_AND_NETWORK,
    Need.DATA_CLIENT,
)


def _need_unmet(check: Check, ctx: Context) -> str | None:
    """The reason a check cannot run, or None if it can."""
    if check.needs is Need.NOTHING:
        return None
    # '--offline' is the user's own choice, so it is the reason given for a
    # network check even when the configuration did not load either
    if ctx.offline and check.needs in _NETWORK_NEEDS:
        return "--offline"
    if check.needs is Need.NETWORK:
        return None
    if not ctx.config_loaded:
        return "configuration did not load"
    if check.needs in (Need.CONFIG, Need.CONFIG_AND_NETWORK):
        return None
    has_credentials = (
        ctx.config_common is not None
        and ctx.config_common.key
        and ctx.config_common.secret
    )
    if check.needs in (Need.CREDENTIALS, Need.CREDENTIALS_AND_NETWORK):
        return None if has_credentials else "no credentials"
    if check.needs is Need.DATA_CLIENT:
        if ctx.data_client_error is not None:
            return ctx.data_client_error
        if ctx.data_client is None or not ctx.data_client.remote:
            return "no data client configured"
        return None
    return None


CONFIG_LOADS = "Configuration loads"
DATA_CLIENT_GROUP = "Data client"


def _run_one(check: Check, ctx: Context) -> Result:
    reason = _need_unmet(check, ctx)
    if reason is not None:
        return Result(Status.SKIP, reason)
    try:
        return check.run(ctx)
    except SystemExit as e:  # a check that trips an exit() is a row too
        if ctx.debug:
            raise
        return Result(Status.FAIL, f"exited with status {e.code}")
    except Exception as e:  # a check's failure is a row, not a crash
        if ctx.debug:
            raise
        return Result(Status.FAIL, str(e) or type(e).__name__)


def run_checks(
    ctx: Context, checks: tuple[Check, ...] | None = None
) -> list[tuple[Check, Result]]:
    """
    Run the checks in order and return a row for each. The one named
    CONFIG_LOADS is run first, whatever its place, because a check listed
    ahead of it may need the configuration (Certificates does). Its row
    stays in its place, and dynamic_checks(), which exist only once the
    configuration is known, open the Data client group (they belong to it),
    or follow the last check of CONFIG_LOADS's group when the tuple has no
    Data client check, so that the JSON lists the rows in the order the
    table, which groups them, shows them.
    """
    checks = CHECKS if checks is None else checks
    early: dict[str, Result] = {
        check.name: _run_one(check, ctx)
        for check in checks
        if check.name == CONFIG_LOADS
    }
    config_group = next((c.group for c in checks if c.name == CONFIG_LOADS), None)
    last_of_group = max(
        (i for i, c in enumerate(checks) if c.group == config_group), default=-1
    )
    first_data_client = next(
        (i for i, c in enumerate(checks) if c.group == DATA_CLIENT_GROUP), None
    )
    insert_before = first_data_client
    insert_after = last_of_group if first_data_client is None else None

    def dynamic_rows() -> list[tuple[Check, Result]]:
        return [(extra, _run_one(extra, ctx)) for extra in dynamic_checks(ctx)]

    rows: list[tuple[Check, Result]] = []
    for i, check in enumerate(checks):
        if early and i == insert_before:
            rows.extend(dynamic_rows())
        rows.append((check, early.get(check.name) or _run_one(check, ctx)))
        if early and i == insert_after:
            rows.extend(dynamic_rows())
    return rows


# --- Installation --------------------------------------------------------


def check_python_version(ctx: Context) -> Result:
    version = tuple(sys.version_info[:3])
    text = ".".join(map(str, version))
    if version[:2] < PYTHON_MIN_VERSION:
        return Result(
            Status.FAIL,
            text,
            f"Install Python {'.'.join(map(str, PYTHON_MIN_VERSION))} or later",
        )
    if version[:2] > PYTHON_MAX_TESTED_VERSION:
        return Result(
            Status.WARN,
            text,
            f"Newer than the highest version tested ({'.'.join(map(str, PYTHON_MAX_TESTED_VERSION))})",
        )
    return Result(Status.OK, text)


def check_install_kind(ctx: Context) -> Result:
    exe = sys.executable.replace("\\", "/")
    if "/pipx/venvs/" in exe:
        return Result(Status.OK, f"pipx ({sys.prefix})")
    if "/uv/tools/" in exe:
        return Result(Status.OK, f"uv tool ({sys.prefix})")
    if sys.prefix != sys.base_prefix:
        return Result(Status.OK, f"virtual environment ({sys.prefix})")
    return Result(
        Status.WARN,
        f"system Python ({exe})",
        "Install with pipx or uv so the CLI's dependencies cannot collide with"
        " the system's: see the README's Installation section",
    )


def check_cli_and_sdk_versions(ctx: Context) -> Result:
    # From the package metadata, so that the row is there even when the SDK
    # will not import, which the next row reports
    return Result(Status.OK, f"CLI {CLI_VERSION}, SDK {sdk_version()}")


def check_sdk_imports(ctx: Context) -> Result:
    """
    Whether the YellowDog SDK imports, which every Platform command needs:
    one missing, half-upgraded or broken is reported here, and the checks
    that use it skip, rather than the doctor itself failing to start.
    """
    try:
        from yellowdog_client import PlatformClient  # noqa: F401
    except Exception as e:
        ctx.sdk_error = " ".join(str(e).split()) or type(e).__name__
        return Result(
            Status.FAIL,
            ctx.sdk_error,
            "Reinstall the CLI with the command you installed it with (e.g."
            " pipx reinstall yellowdog-cli), which reinstalls the SDK it needs",
        )
    return Result(Status.OK, "imports")


def _pypi_latest_version(timeout: float) -> str:
    response = requests.get(PYPI_PROJECT_URL, timeout=timeout)
    response.raise_for_status()
    return response.json()["info"]["version"]


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in text.split(".") if part.isdigit())


def check_newer_cli_on_pypi(ctx: Context) -> Result:
    try:
        latest = _pypi_latest_version(min(ctx.timeout, 5))
    except Exception as e:
        return Result(Status.SKIP, f"PyPI not reachable ({type(e).__name__})")
    if _version_tuple(latest) > _version_tuple(CLI_VERSION):
        return Result(
            Status.WARN,
            f"{latest} available, {CLI_VERSION} installed",
            "Update with the command you installed with, e.g. pipx upgrade yellowdog-cli",
        )
    return Result(Status.OK, f"up to date ({CLI_VERSION})")


def _module_is_installed(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _check_extra(module: str, guard: Callable[[], None]) -> Result:
    if not _module_is_installed(module):
        return Result(Status.OK, "not installed (optional)")
    try:
        guard()
    except ImportError as e:
        return Result(Status.FAIL, "installed but will not load", str(e))
    return Result(Status.OK, "installed")


def check_extra_jsonnet(ctx: Context) -> Result:
    return _check_extra(EXTRA_PROBES["jsonnet"], check_jsonnet_import)


def check_extra_cloudwizard(ctx: Context) -> Result:
    return _check_extra(EXTRA_PROBES["cloudwizard"], check_cloudwizard_imports)


def check_extra_commander(ctx: Context) -> Result:
    return _check_extra(EXTRA_PROBES["commander"], check_commander_imports)


def check_extra_mcp(ctx: Context) -> Result:
    return _check_extra(EXTRA_PROBES["mcp"], check_mcp_imports)


def check_rclone(ctx: Context) -> Result:
    found = find_rclone()
    if found is None:
        return Result(
            Status.WARN,
            "not found",
            "yd-upload, yd-download, yd-delete, yd-ls and yd-copy need it; run"
            " yd-submit --upgrade-rclone or install rclone on PATH",
        )
    path, source = found
    return Result(Status.OK, f"{rclone_version()} ({path}, {source})")


_PAC_REMEDY = (
    "Check the PAC file the system's proxy settings name, or turn PAC off"
    " (drop --pac, or set usePAC = false in [common])"
)


def _resolve_pac_proxy(url: str, timeout: float) -> str | Result | None:
    """
    The proxy PAC gives for url, resolved as wrapper.set_proxy() does, and
    kept in HTTPS_PROXY so that requests and the SDK's session, which read
    the environment at request time, use it for every later live check.
    None if nothing resolves; a FAIL Result if the resolution itself fails.
    """

    def resolve() -> str | None:
        with pac_context_for_url(url):
            return os.getenv("HTTPS_PROXY")

    try:
        outcome = with_timeout(resolve, timeout)
    except Exception as e:  # a PAC file that cannot be fetched or run
        return Result(Status.FAIL, f"PAC: {e or type(e).__name__}", _PAC_REMEDY)
    if isinstance(outcome, Result):  # fetching the PAC file is a network call
        return Result(Status.FAIL, f"PAC: {outcome.detail}", _PAC_REMEDY)
    if outcome is not None:
        os.environ["HTTPS_PROXY"] = outcome
    return outcome


def _environment_proxy() -> str | None:
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")


def check_proxy(ctx: Context) -> Result:
    """
    The proxy the live checks, and every command, will use: HTTPS_PROXY, or
    with PAC on (--pac or usePAC) the proxy PAC resolves for the API URL,
    which is then kept in HTTPS_PROXY for the later checks. It runs after
    the configuration has loaded (run_checks sees to that), since whether
    PAC is on is the configuration's to say.
    """
    cfg = ctx.config_common
    if cfg is not None and cfg.use_pac:
        if ctx.offline:
            return Result(Status.OK, "PAC enabled (not resolved: --offline)")
        resolved = _resolve_pac_proxy(cfg.url, ctx.timeout)
        if isinstance(resolved, Result):
            return resolved
        if resolved is not None:
            return Result(
                Status.OK, f"PAC resolved HTTPS_PROXY={resolved} for {cfg.url}"
            )
        return Result(
            Status.WARN,
            f"PAC enabled but no proxy resolved for {cfg.url};"
            " commands will connect directly",
            _PAC_REMEDY,
        )
    proxy = _environment_proxy()
    shown = f"HTTPS_PROXY={proxy}" if proxy else "none"
    if cfg is None:
        shown += " (PAC status unknown: configuration did not load)"
    return Result(Status.OK, shown)


def check_certificates(ctx: Context) -> Result:
    bundle = os.environ.get(
        "REQUESTS_CA_BUNDLE"
    )  # load_config sets it from the 'certificates' property
    if not bundle:
        return Result(Status.OK, "system default")
    if not os.path.isfile(bundle):
        return Result(
            Status.FAIL,
            f"{bundle} is not a readable file",
            "Fix REQUESTS_CA_BUNDLE or the 'certificates' property in [common]",
        )
    return Result(Status.OK, bundle)


# --- Configuration -------------------------------------------------------


def check_config_loads(ctx: Context) -> Result:
    """
    Import load_config and load the common section leniently, capturing what
    either prints, because both exit on a broken configuration and the exit's
    message is the diagnosis. The only load_config_common() call in the
    doctor: CONFIG_SOURCES is accurate only for the first in a process.
    """
    captured = io.StringIO()
    try:
        with (
            contextlib.redirect_stdout(captured),
            contextlib.redirect_stderr(captured),
        ):
            from yellowdog_cli.utils import load_config

            ctx.config_common = load_config.load_config_common(strict=False)
    except SystemExit:
        ctx.config_error = _captured_message(captured.getvalue())
        # the remedy carries the error too, since --quiet prints it alone
        return Result(
            Status.FAIL,
            ctx.config_error,
            f"{ctx.config_error} — fix the configuration file or the option it names",
        )
    ctx.config_loaded = True
    _load_data_client_profiles(ctx, load_config)
    _load_data_client_under_test(ctx, load_config)

    if not os.path.isfile(load_config.CONFIG_FILE):
        return Result(Status.OK, "no file, environment only")
    if ARGS_PARSER.no_config:
        return Result(Status.OK, f"{load_config.CONFIG_FILE} ignored, environment only")
    return Result(Status.OK, load_config.CONFIG_FILE)


CONFIG_SCHEMA_SHOWN = 3  # violations named in the detail; the rest counted


def check_config_schema(ctx: Context) -> Result:
    """
    The configuration file against the config schema, every section: what
    a command would warn of as it starts. Read from the file as written, the
    '--property' overrides applied, as those warnings are.
    """
    import fastjsonschema

    from yellowdog_cli.utils import load_config, spec_validation
    from yellowdog_cli.utils.spec_properties import ALL_CONFIG_SECTIONS
    from yellowdog_cli.utils.spec_schema import SchemaGenerationError

    document = load_config.config_as_written()
    if document is None:
        return Result(Status.OK, "no configuration file")
    try:
        violations = spec_validation.validate_config(document, ALL_CONFIG_SECTIONS)
    except (SchemaGenerationError, fastjsonschema.JsonSchemaDefinitionException) as e:
        return Result(
            Status.WARN,
            f"the schema could not be built: {e}",
            "Run 'yd-schema config' to see why; the configuration may be fine",
        )
    if not violations:
        return Result(Status.OK, "no violations")
    shown = "; ".join(
        f"{v.path}: {v.message}" for v in violations[:CONFIG_SCHEMA_SHOWN]
    )
    more = len(violations) - CONFIG_SCHEMA_SHOWN
    count = f"{len(violations)} violation{'s' if len(violations) != 1 else ''}"
    return Result(
        Status.WARN,
        f"{count}: {shown}" + (f"; and {more} more" if more > 0 else ""),
        "Every one is reported as a warning when a command runs;"
        " 'yd-schema config' prints the schema",
    )


def _captured_message(text: str) -> str:
    """
    What a failed load printed, as one line: the log prefix (timestamp and
    ERROR marker) dropped, and the console's line wrapping undone.
    """
    if ERROR_MARKER in text:
        text = text.split(ERROR_MARKER, 1)[1]
    return " ".join(text.split()) or "configuration could not be loaded"


def _load_data_client_profiles(ctx: Context, load_config: Any) -> None:
    """
    Record each data client profile under its row's name: the loaded
    ConfigDataClient, or None and, in profile_errors, what the loader said
    on its way to exiting, which is the row's diagnosis.
    """
    section = load_config.CONFIG_TOML.get(load_config.DATA_CLIENT_SECTION)
    if not section:
        return
    names: list[str | None] = [None]
    names.extend(k for k, v in section.items() if isinstance(v, dict))
    for name in names:
        row_name = "[dataClient]" if name is None else name
        ctx.profiles[row_name] = None
        captured = io.StringIO()
        try:
            with (
                contextlib.redirect_stdout(captured),
                contextlib.redirect_stderr(captured),
            ):
                ctx.profiles[row_name] = (
                    load_config.load_config_data_client_for_profile(name)
                )
        except (SystemExit, Exception):  # the loader prints and exits on a bad one
            ctx.profile_errors[row_name] = _captured_message(captured.getvalue())


def _load_data_client_under_test(ctx: Context, load_config: Any) -> None:
    """
    Load the data client a data client command would use, with the loader
    they all use: it honours YD_DATA_CLIENT, and needs no [dataClient]
    section, since YD_DATA_CLIENT_REMOTE and its siblings can configure one
    from the environment alone. One that fails to load leaves data_client
    None, and what it printed becomes the Remote reachable row's reason.
    """
    name = getattr(ARGS_PARSER, "data_client_profile", None) or os.environ.get(
        YD_DATA_CLIENT
    )
    ctx.data_client_name = name or "[dataClient]"
    captured = io.StringIO()
    try:
        with (
            contextlib.redirect_stdout(captured),
            contextlib.redirect_stderr(captured),
        ):
            ctx.data_client = load_config.load_config_data_client()
    except (SystemExit, Exception):  # the loader prints and exits on a bad profile
        ctx.data_client = None
        ctx.data_client_error = (
            f"profile {ctx.data_client_name} did not load: "
            + _captured_message(captured.getvalue())
        )


def check_config_value(prop: str) -> Callable[[Context], Result]:
    """A check reporting one [common] value and where it came from."""
    attribute = {NAME_TAG: "name_tag"}.get(prop, prop)

    def run(ctx: Context) -> Result:
        from yellowdog_cli.utils import load_config
        from yellowdog_cli.utils.settings import REDACTED_VALUE

        value = getattr(ctx.config_common, attribute)
        if value is None:
            return Result(
                Status.FAIL,
                "not set",
                f"Set it with --{prop}, the YD_{prop.upper()} environment"
                f" variable, or '{prop}' in [common]",
            )
        shown = REDACTED_VALUE if prop == SECRET else str(value)
        source = load_config.CONFIG_SOURCES.get(prop, "not set")
        return Result(Status.OK, f"{shown} ({source})")

    return run


def check_variable_references(ctx: Context) -> Result:
    from yellowdog_cli.utils import load_config
    from yellowdog_cli.utils.variable_substitution import undefined_variable_references

    undefined = undefined_variable_references(load_config.CONFIG_TOML)
    if undefined:
        return Result(
            Status.WARN,
            "undefined: " + ", ".join(undefined),
            "Define each with -v name=value, a YD_VAR_ variable, or [common.variables]",
        )
    return Result(Status.OK, "all resolved")


def check_dotenv(ctx: Context) -> Result:
    from yellowdog_cli.utils.misc_utils import dotenv_file_path

    path = dotenv_file_path()
    return Result(Status.OK, path if path else "none")


def check_tag_is_a_legal_name(ctx: Context) -> Result:
    from yellowdog_cli.utils.misc_utils import format_yd_name

    tag = ctx.config_common.name_tag
    formatted = format_yd_name(tag, add_prefix=False)
    if formatted != tag:
        return Result(
            Status.WARN,
            f"'{tag}' would be used as '{formatted}'",
            "Use lower-case letters, digits, '-' and '_' in the tag",
        )
    return Result(Status.OK, tag)


# shown_remote() lives in rclone_utils.py: yd-variables renders an inline
# remote the same way


def _profile_remedy(name: str, message: str) -> str:
    """Name the profile, and the property to fix when the message names one."""
    section = name if name == "[dataClient]" else f"[dataClient.{name}]"
    named = [
        prop
        for prop in (DATA_CLIENT_REMOTE, DATA_CLIENT_BUCKET, DATA_CLIENT_PREFIX)
        if re.search(rf"\b{prop}\b", message)
    ]
    if len(named) == 1:
        return (
            f"Fix '{named[0]}' in {section}, or the YD_DATA_CLIENT_ variable setting it"
        )
    return (
        f"Fix the values in {section}, or the YD_DATA_CLIENT_ variables that"
        " override them, as the message says"
    )


def _profile_check(name: str) -> Callable[[Context], Result]:
    def run(ctx: Context) -> Result:
        from yellowdog_cli.utils.rclone_utils import make_rclone, parse_rclone_config

        profile = ctx.profiles.get(name)
        if profile is None:
            message = ctx.profile_errors.get(name, "no reason given")
            return Result(
                Status.FAIL,
                f"could not be loaded: {message}",
                _profile_remedy(name, message),
            )
        location = (
            f"{shown_remote(profile.remote or '')}"
            f" {profile.bucket or ''}/{profile.prefix or ''}"
        )
        location = location.strip().rstrip("/")
        if not profile.remote:
            return Result(
                Status.FAIL,
                location,
                "Set 'remote' in [dataClient] or YD_DATA_CLIENT_REMOTE",
            )
        remote_name, inline = parse_rclone_config(profile.remote)
        if inline is None:  # a named remote must exist in rclone's own config
            if find_rclone() is None:
                return Result(Status.SKIP, "rclone not found")
            try:
                names = [remote.name for remote in make_rclone(None).listremotes()]
            except FileNotFoundError:  # no rclone.conf at all
                names = []
            if remote_name.rstrip(":") not in names:
                return Result(
                    Status.FAIL,
                    f"named remote '{remote_name}' is not in rclone's"
                    f" configuration ({location})",
                    "Run 'rclone config' to define it, or use an inline"
                    " connection string",
                )
        return Result(Status.OK, location)

    return run


# --- Platform ------------------------------------------------------------


def check_platform_reachable(ctx: Context) -> Result:
    result = _platform_reachable(ctx)
    ctx.platform_reachable = result.status is not Status.FAIL
    return result


def _platform_reachable(ctx: Context) -> Result:
    """
    A GET of the API URL through whatever HTTPS_PROXY the environment holds,
    which, with PAC on, the Proxy row has already set from PAC.
    """
    url = ctx.config_common.url
    try:
        outcome = with_timeout(
            lambda: requests.get(url, timeout=ctx.timeout), ctx.timeout
        )
    except requests.RequestException as e:
        return Result(
            Status.FAIL,
            f"{url}: {e}",
            "Check the URL, DNS, proxy (HTTPS_PROXY / --pac) and certificates",
        )
    if isinstance(outcome, Result):  # the timeout, which also bounds DNS
        return outcome
    answered = f"{url} answered HTTP {outcome.status_code}"
    proxy = _environment_proxy()
    if ctx.config_common.use_pac and proxy:
        answered += f" via HTTPS_PROXY={proxy}"
    if outcome.status_code >= 500:
        # It answered, but is in trouble: the commands may fail until it is not
        return Result(
            Status.WARN,
            answered,
            "The platform reported a server error; try again later, and if it"
            " persists, contact YellowDog support",
        )
    return Result(Status.OK, answered)


def _build_client(cfg: Any) -> Any:
    from yellowdog_client import PlatformClient
    from yellowdog_client.model import ApiKey, ServicesSchema

    return PlatformClient.create(
        ServicesSchema(defaultUrl=cfg.url), ApiKey(cfg.key, cfg.secret)
    )


def check_authenticated(ctx: Context) -> Result:
    # the SDK retries a refused connection until the budget runs out, which
    # would cost a second timeout to report what Reachable already has
    if ctx.platform_reachable is False:
        return Result(Status.SKIP, "platform not reachable")
    if ctx.sdk_error is not None:
        return Result(Status.SKIP, "SDK did not import")
    client = _build_client(ctx.config_common)
    try:
        outcome = with_timeout(
            client.application_client.get_application_details, ctx.timeout
        )
    except Exception as e:
        # Classified as every command classifies a failure, by its type and
        # status rather than its text
        detail, remedy = _AUTHENTICATION_FAILURES.get(
            classify(e), (" ".join(str(e).split()) or type(e).__name__, None)
        )
        return Result(Status.FAIL, detail, remedy)
    if isinstance(outcome, Result):  # the timeout
        return outcome
    ctx.client, ctx.application = client, outcome
    return Result(
        Status.OK, f"application '{outcome.name}' in account '{outcome.accountName}'"
    )


_AUTHENTICATION_FAILURES: dict[ExitCode, tuple[str, str]] = {
    ExitCode.AUTHENTICATION: (
        "key or secret not recognised",
        "Check the Application key and secret, and that the Application still exists",
    ),
    ExitCode.PERMISSION: (
        "the Application is not permitted to read its own details",
        "Add the Application to a group that carries a role, in the YellowDog Portal",
    ),
    ExitCode.CONNECTION: (
        "the connection failed",
        "Check the URL, DNS, proxy (HTTPS_PROXY / --pac) and certificates",
    ),
    ExitCode.PLATFORM: (
        "the platform reported a server error",
        "Try again later, and if it persists, contact YellowDog support",
    ),
}


def check_groups_and_roles(ctx: Context) -> Result:
    from yellowdog_cli.utils.entity_utils import (
        get_all_roles_and_namespaces_for_application,
        get_application_group_summaries,
    )

    if ctx.application is None:
        return Result(Status.SKIP, "not authenticated")
    app_id = ctx.application.id
    outcome = with_timeout(
        lambda: (
            [g.name for g in get_application_group_summaries(ctx.client, app_id)],
            get_all_roles_and_namespaces_for_application(ctx.client, app_id),
        ),
        ctx.timeout,
    )
    if isinstance(outcome, Result):
        return outcome
    groups, roles = outcome
    group_text = "groups: " + (", ".join(groups) or "none")
    if not roles:
        return Result(
            Status.WARN,
            f"{group_text}; roles: none",
            "Add the Application to a group that carries a role for the"
            " namespaces it needs",
        )
    role_text = ", ".join(f"{role} ({', '.join(ns)})" for role, ns in roles.items())
    return Result(Status.OK, f"{group_text}; roles: {role_text}")


def check_namespace_granted(ctx: Context) -> Result:
    if ctx.application is None:
        return Result(Status.SKIP, "not authenticated")
    namespace = ctx.config_common.namespace
    if ctx.application.allNamespacesReadable or namespace in (
        ctx.application.readableNamespaces or []
    ):
        return Result(Status.OK, namespace)
    return Result(
        Status.WARN,
        f"'{namespace}' is not readable by this application",
        "Give the Application a role scoped to this namespace, or set a"
        " namespace it can read",
    )


# --- Data client remote --------------------------------------------------


def _rclone_for_config(config: Any) -> tuple[str, Any]:
    from yellowdog_cli.utils.dataclient_utils import _rclone_for_config as real

    return real(config)


def check_data_client_remote(ctx: Context) -> Result:
    """
    Whether the data client commands can reach where they work: the
    configured prefix, as resolve_remote_path() gives it to them, rather
    than the bucket's root, which a policy scoped to the prefix may refuse
    although every command would work. A prefix not created yet is OK:
    the first upload creates it.
    """
    from yellowdog_cli.utils.dataclient_utils import (
        remote_stat,
        resolve_bucket_path,
        resolve_remote_path,
    )

    profile = f"profile {ctx.data_client_name}"
    _, rclone = _rclone_for_config(ctx.data_client)
    target = resolve_remote_path(ctx.data_client)
    try:
        outcome = with_timeout(lambda: remote_stat(rclone, target), ctx.timeout)
    except Exception as e:
        lines = [line for line in str(e).splitlines() if line.strip()]
        return Result(
            Status.FAIL,
            f"{target} ({profile}): {lines[-1].strip() if lines else type(e).__name__}",
            "Check the remote's credentials, the bucket's name, and access to it",
        )
    if isinstance(outcome, Result):
        return outcome
    if outcome is None:
        # The prefix is not there: fine if the bucket is, which the first
        # upload then writes into, but a bucket that is not there (a typo
        # in its name) is no 'not created yet'
        if (ctx.data_client.bucket or "").strip("/"):
            bucket_path = resolve_bucket_path(ctx.data_client)
            try:
                found = with_timeout(
                    lambda: remote_stat(rclone, bucket_path), ctx.timeout
                )
            except Exception as e:
                lines = [line for line in str(e).splitlines() if line.strip()]
                return Result(
                    Status.FAIL,
                    f"{bucket_path} ({profile}): "
                    f"{lines[-1].strip() if lines else type(e).__name__}",
                    "Check the remote's credentials, the bucket's name, and"
                    " access to it",
                )
            if isinstance(found, Result):
                return found
            if found is None:
                return Result(
                    Status.FAIL,
                    f"{bucket_path} ({profile}): bucket not found",
                    "Check the bucket's name in [dataClient], or YD_DATA_CLIENT_BUCKET",
                )
        return Result(Status.OK, f"{target} reachable, not created yet ({profile})")
    return Result(Status.OK, f"{target} reachable ({profile})")


CHECKS: tuple[Check, ...] = (
    Check("Python version", "Installation", Need.NOTHING, check_python_version),
    Check("Install kind", "Installation", Need.NOTHING, check_install_kind),
    Check(
        "CLI and SDK versions", "Installation", Need.NOTHING, check_cli_and_sdk_versions
    ),
    Check("SDK imports", "Installation", Need.NOTHING, check_sdk_imports),
    Check("Jsonnet", "Installation", Need.NOTHING, check_extra_jsonnet),
    Check("Cloud Wizard", "Installation", Need.NOTHING, check_extra_cloudwizard),
    Check("Commander", "Installation", Need.NOTHING, check_extra_commander),
    Check("MCP Server", "Installation", Need.NOTHING, check_extra_mcp),
    Check("rclone", "Installation", Need.NOTHING, check_rclone),
    # Ahead of the PyPI check, so that the proxy PAC resolves, kept in
    # HTTPS_PROXY, is the one it goes through
    Check("Proxy", "Installation", Need.NOTHING, check_proxy),
    Check("Certificates", "Installation", Need.CONFIG, check_certificates),
    Check("Newer CLI on PyPI", "Installation", Need.NETWORK, check_newer_cli_on_pypi),
    Check(CONFIG_LOADS, "Configuration", Need.NOTHING, check_config_loads),
    Check("Config schema", "Configuration", Need.CONFIG, check_config_schema),
    Check("Key", "Configuration", Need.CONFIG, check_config_value(KEY)),
    Check("Secret", "Configuration", Need.CONFIG, check_config_value(SECRET)),
    Check("Namespace", "Configuration", Need.CONFIG, check_config_value(NAMESPACE)),
    Check("Tag", "Configuration", Need.CONFIG, check_config_value(NAME_TAG)),
    Check("URL", "Configuration", Need.CONFIG, check_config_value(URL)),
    Check(
        "Variable references", "Configuration", Need.CONFIG, check_variable_references
    ),
    Check(".env file", "Configuration", Need.CONFIG, check_dotenv),
    # The spec lists it under Platform, but it needs no network
    Check(
        "Tag is a legal name", "Configuration", Need.CONFIG, check_tag_is_a_legal_name
    ),
    Check("Reachable", "Platform", Need.CONFIG_AND_NETWORK, check_platform_reachable),
    Check(
        "Authenticated", "Platform", Need.CREDENTIALS_AND_NETWORK, check_authenticated
    ),
    Check(
        "Groups and roles",
        "Platform",
        Need.CREDENTIALS_AND_NETWORK,
        check_groups_and_roles,
    ),
    Check(
        "Namespace granted",
        "Platform",
        Need.CREDENTIALS_AND_NETWORK,
        check_namespace_granted,
    ),
    Check(
        "Remote reachable",
        DATA_CLIENT_GROUP,
        Need.DATA_CLIENT,
        check_data_client_remote,
    ),
)


def dynamic_checks(ctx: Context) -> tuple[Check, ...]:
    """
    The checks whose names come from the configuration: one per data client
    profile, '[dataClient]' first, or a single SKIP row when the
    configuration loaded with no [dataClient] section. Empty until
    check_config_loads has run, and when the configuration did not load.
    """
    if not ctx.profiles:
        if not ctx.config_loaded:
            return ()
        return (
            Check(
                "Data client profile",
                "Data client",
                Need.CONFIG,
                lambda _: Result(Status.SKIP, "no [dataClient] section"),
            ),
        )
    return tuple(
        Check(
            f"Data client profile {name}",
            "Data client",
            Need.CONFIG,
            _profile_check(name),
        )
        for name in ctx.profiles
    )
