"""
Handle optional imports.
"""


def check_jsonnet_import():
    # Jsonnet is not installed by default, due to a binary build requirement
    # on some platforms.
    #
    # '_jsonnet' is a compiled extension, so "missing" and "present but will not
    # load" are different problems with different remedies, and telling someone to
    # pip install a package they already have sends them the wrong way.
    try:
        from _jsonnet import evaluate_file  # noqa: F401
    except ModuleNotFoundError:
        raise ImportError(
            "Jsonnet support is not included by default. The 'jsonnet' Python package"
            " can usually be installed by adding the option to pip:"
            ' pip install -U "yellowdog-cli[jsonnet]"'
            " or installed separately using: pip install -U jsonnet"
        )
    except ImportError as exc:
        # The package is there but its extension module cannot be loaded: a
        # missing C++ runtime, or a wheel built for a different Python or
        # architecture. Reinstalling the same wheel will not change any of that.
        raise ImportError(
            f"The 'jsonnet' package is installed, but its compiled extension will"
            f" not load: {exc}\n"
            "Reinstalling the same wheel is unlikely to help. Either a system"
            " library is missing — on Debian/Ubuntu, 'sudo apt-get install -y"
            " libstdc++6' — or the wheel does not match this Python or CPU"
            " architecture, in which case rebuild it from source with:\n"
            "    pip install -U --no-binary :all: jsonnet\n"
            "That compiles Jsonnet, so it needs a C++ compiler ('build-essential'"
            " on Debian/Ubuntu)."
        )


def check_cloudwizard_imports():
    # The cloud provider SDKs for Cloud Wizard are not installed by default.
    try:
        import boto3  # noqa: F401  # One example package required for Cloud Wizard
    except ImportError:
        raise ImportError(
            "The cloud provider SDKs needed for Cloud Wizard are not installed"
            " by default. They can be installed by adding the option to pip:"
            ' pip install -U "yellowdog-cli[cloudwizard]"'
        )


def check_commander_imports():
    # PyQt6 is not installed by default (heavy Qt binaries). It is only needed
    # for the yd-commander GUI.
    #
    # Probe QtWidgets rather than the top-level 'PyQt6' package. The package
    # itself imports without touching Qt's shared libraries, so a machine that
    # has the wheel but not those libraries passes a top-level check and then
    # fails with a traceback from inside commander.py's own imports. QtWidgets
    # pulls in the runtime (and QtGui with it), so it fails here instead, where
    # the message can say something useful.
    try:
        import PyQt6.QtWidgets  # noqa: F401
    except ModuleNotFoundError:
        raise ImportError(
            "The Commander GUI is not installed by default. It can be installed"
            " by adding the option to pip:"
            ' pip install -U "yellowdog-cli[commander]"'
        )
    except ImportError as exc:
        # PyQt6 is present but Qt will not load. That is a missing system
        # library, which no pip install will fix, so say so and name it: the
        # exception carries the first library Qt looked for and did not find.
        raise ImportError(
            f"The Commander GUI is installed, but Qt cannot start here: {exc}\n"
            "This is a system library rather than a Python package. Qt needs it"
            " even without a display, because it belongs to Qt itself and not to"
            " the graphics stack. On Debian/Ubuntu:\n"
            "    sudo apt-get install -y libgl1 libegl1 libglib2.0-0t64"
            " libxkbcommon0 libdbus-1-3 libfontconfig1\n"
            "On releases before Ubuntu 24.04 the glib package is 'libglib2.0-0',"
            " and before 20.04 libGL comes from 'libgl1-mesa-glx'. If a further"
            " library is named next time, install that too: the package is"
            " usually the library's name with the version moved to the end, so"
            " 'libxkbcommon.so.0' comes from 'libxkbcommon0'."
        )
