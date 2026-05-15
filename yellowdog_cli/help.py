#!/usr/bin/env python3

"""
List all available yd-* commands and their purposes.
"""

from yellowdog_cli._version import __version__

# Ordered list of (command, one-line description) pairs.
_COMMANDS: list[tuple[str, str]] = [
    ("yd-abort", "Abort running Tasks"),
    ("yd-application", "Report details of the current Application"),
    ("yd-boost", "Boost Allowances"),
    ("yd-cancel", "Cancel Work Requirements"),
    ("yd-cloudwizard", "Set up cloud accounts and YellowDog resources"),
    ("yd-compare", "Compare a Work Requirement or Task Group against Worker Pool(s)"),
    ("yd-create", "Create and update resources"),
    ("yd-delete", "Delete remote data client files and directories"),
    ("yd-download", "Download files from a remote data client"),
    ("yd-finish", "Finish Work Requirements"),
    ("yd-follow", "Follow event streams"),
    ("yd-format-json", "Format JSON files using a compact encoder"),
    ("yd-help", "List available yd-* commands and their purposes"),
    ("yd-hold", "Hold (pause) running Work Requirements"),
    ("yd-instantiate", "Instantiate a Compute Requirement"),
    ("yd-jsonnet2json", "Convert a Jsonnet file to JSON"),
    ("yd-list", "List YellowDog items"),
    ("yd-ls", "List remote data client files and directories"),
    ("yd-nodeaction", "Submit Node Actions to Worker Pool nodes"),
    ("yd-provision", "Provision a Worker Pool"),
    ("yd-remove", "Remove resources"),
    ("yd-resize", "Resize Worker Pools and Compute Requirements"),
    ("yd-show", "Show the JSON details of entities referenced by their YDIDs"),
    ("yd-shutdown", "Shut down Worker Pools and Nodes"),
    ("yd-start", "Start held (paused) Work Requirements"),
    ("yd-submit", "Submit a Work Requirement"),
    ("yd-terminate", "Terminate Compute Requirements, Instances or Nodes"),
    ("yd-upload", "Upload files to a remote data client"),
    ("yd-version", "Report version information"),
]


def main():
    col_width = max(len(cmd) for cmd, _ in _COMMANDS)
    print(f"\nYellowDog CLI v{__version__} — available commands:\n")
    for cmd, desc in _COMMANDS:
        print(f"  {cmd:<{col_width}}  {desc}")
    print()


if __name__ == "__main__":
    main()
