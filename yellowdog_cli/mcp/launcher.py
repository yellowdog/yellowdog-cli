"""
yd-mcp's entry point: the launch options, then the missing-extra guard, then
the server. Free of the 'mcp' package, the SDK and Qt, so '--help' and the
install hint work without the extra installed.
"""

import argparse
import os
import sys

from yellowdog_cli.mcp.tools import ServerSettings
from yellowdog_cli.utils.check_imports import check_mcp_imports

TRANSPORTS = ("stdio",)  # streamable-http is phase 2


def _existing_file(value: str) -> str:
    if not os.path.isfile(value):
        raise argparse.ArgumentTypeError(f"file not found: {value}")
    return os.path.abspath(value)


def _variable(value: str) -> str:
    name, separator, _ = value.partition("=")
    if not separator or not name:
        raise argparse.ArgumentTypeError(f"a variable is name=value, not '{value}'")
    return value


ONCE = "give the configuration file once, either as an argument or with -c"


class _Once(argparse.Action):
    """Store the value, refusing a second one rather than keeping the last."""

    def __call__(self, parser, namespace, values, option_string=None):
        if getattr(namespace, self.dest) is not None:
            parser.error(ONCE)
        setattr(namespace, self.dest, values)


def parse_args(argv: list[str] | None = None) -> ServerSettings:
    parser = argparse.ArgumentParser(
        prog="yd-mcp",
        description=(
            "Run the YellowDog MCP server: every yd-* command as a tool, each call"
            " run as a yd-* command with --json."
        ),
        epilog="The namespace, tag and variables are given to every command the tools run.",
    )
    parser.add_argument(
        "config_file",
        nargs="?",
        metavar="<config_file.toml>",
        type=_existing_file,
        help="the TOML configuration file the commands use; without one, the environment alone",
    )
    parser.add_argument(
        "--config",
        "-c",
        dest="config_option",
        action=_Once,
        metavar="<config_file.toml>",
        type=_existing_file,
        help="the configuration file, as an option rather than an argument",
    )
    parser.add_argument(
        "--namespace",
        "-n",
        metavar="<namespace>",
        help="the namespace for every command",
    )
    parser.add_argument(
        "--tag", "-t", metavar="<tag>", help="the tag for every command"
    )
    parser.add_argument(
        "--variable",
        "-v",
        action="append",
        default=[],
        metavar="<name=value>",
        type=_variable,
        help="a variable substitution for every command; can be repeated",
    )
    parser.add_argument(
        "--transport",
        choices=TRANSPORTS,
        default="stdio",
        help="the MCP transport (stdio only, for now)",
    )
    args = parser.parse_args(argv)
    if args.config_file is not None and args.config_option is not None:
        parser.error(ONCE)
    return ServerSettings(
        config_file=args.config_file or args.config_option,
        namespace=args.namespace,
        tag=args.tag,
        variables=tuple(args.variable),
        transport=args.transport,
    )


def main() -> None:
    settings = parse_args()
    try:
        check_mcp_imports()
    except ImportError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

    # Imported only after the guard passes (this import pulls in 'mcp')
    from yellowdog_cli.mcp.server import run_server

    run_server(settings)


if __name__ == "__main__":
    main()
