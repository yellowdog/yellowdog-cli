"""
Handle optional imports.
"""


def check_jsonnet_import():
    # Jsonnet is not installed by default, due to a binary build requirement
    # on some platforms.
    try:
        from _jsonnet import evaluate_file  # noqa: F401
    except ImportError:
        raise ImportError(
            "Jsonnet support is not included by default. The 'jsonnet' Python package"
            " can usually be installed by adding the option to pip:"
            ' pip install -U "yellowdog-cli[jsonnet]"'
            " or installed separately using: pip install -U jsonnet"
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
    try:
        import PyQt6  # noqa: F401
    except ImportError:
        raise ImportError(
            "The Commander GUI is not installed by default. It can be installed"
            " by adding the option to pip:"
            ' pip install -U "yellowdog-cli[commander]"'
        )
