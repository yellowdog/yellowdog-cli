"""
utils/lazy.py, and what it is for: importing any of the CLI's modules does
nothing -- parses no command line, reads no configuration file, builds no
client, prints nothing and exits nowhere -- while the wrappers still build
those before the command runs, so errors surface where they always did.
"""

import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils.lazy import Lazy, built, lazy, prepare, value


class TestLazy:
    def test_built_once_on_first_use(self):
        calls = []

        def build():
            calls.append(1)
            return type("Thing", (), {"x": 1})()

        thing = lazy(build)
        assert calls == [] and not built(thing)
        assert thing.x == 1 and thing.x == 1
        assert calls == [1] and built(thing)

    def test_writes_pass_through(self):
        holder = SimpleNamespace(quiet=False)
        proxy = lazy(lambda: holder)
        proxy.quiet = True
        assert holder.quiet is True

    def test_a_failed_build_is_tried_again(self):
        attempts = []

        def build():
            attempts.append(1)
            if len(attempts) == 1:
                raise SystemExit(3)
            return "ok"

        proxy = lazy(build)
        with pytest.raises(SystemExit):
            value(proxy)
        assert value(proxy) == "ok" and len(attempts) == 2

    def test_equality_truthiness_and_repr(self):
        proxy = lazy(lambda: [1, 2])
        assert repr(proxy) == "<not built yet>"
        assert proxy == [1, 2] and bool(proxy)
        assert repr(proxy) == "[1, 2]"

    def test_prepare_builds_only_lazies_marked_for_it(self):
        eager = lazy(lambda: "eager")
        deferred = lazy(lambda: "deferred", prepare=False)
        stand_in = object()
        prepare(eager, deferred, stand_in, None)
        assert built(eager) and not built(deferred)
        assert built(stand_in)  # a test's stand-in counts as built

    def test_value_of_a_plain_object_is_itself(self):
        thing = object()
        assert value(thing) is thing
        assert isinstance(lazy(lambda: 1), Lazy)


# Run in a fresh interpreter: this process built everything at start-up
# (conftest.py), as the tests expect
_IMPORT_EVERYTHING = textwrap.dedent(
    """
    import importlib, pkgutil, sys
    sys.argv = ["yd-submit", "--no-such-option", "-c", "no-such-config.toml"]
    import yellowdog_cli
    skipped = ("yellowdog_cli.commander", "yellowdog_cli.mcp.server")
    for module in pkgutil.walk_packages(yellowdog_cli.__path__, "yellowdog_cli."):
        if module.name.startswith(skipped) or module.name.endswith("__main__"):
            continue
        try:
            importlib.import_module(module.name)
        except ModuleNotFoundError as e:
            # The Cloud Wizard's modules import its extra's cloud SDKs at the
            # top, and tox's environments install them only in part
            if not module.name.startswith("yellowdog_cli.utils.cloudwizard.") or (
                e.name or ""
            ).startswith("yellowdog_cli"):
                raise
    from yellowdog_cli.utils import args, load_config, wrapper
    from yellowdog_cli.utils.lazy import built
    print(
        built(args.ARGS_PARSER),
        "CONFIG_TOML" in vars(load_config),
        built(wrapper.CONFIG_COMMON),
        built(wrapper.CLIENT),
    )
    """
)


def test_importing_every_module_does_nothing():
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_EVERYTHING],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    # Nothing parsed (the option would be refused), read (the file would be
    # missing), built, printed or exited
    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout == "False False False False\n"
