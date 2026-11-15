"""
A child process as Commander starts every one: the system's environment with
CHILD_ENVIRONMENT added, in the directory commands run in. host.py, which
says what those are, stays Qt-free.
"""

from PyQt6.QtCore import QObject, QProcess, QProcessEnvironment

from yellowdog_cli.commander.host import CHILD_ENVIRONMENT

# How long a child is given to exit once asked to (QProcess.terminate()) before
# it is forced to (kill()): by Quit, which waits, and by Stop, which does not
TERMINATE_TIMEOUT_MS = 2000


def child_process(working_dir: str, parent: QObject | None = None) -> QProcess:
    """
    A QProcess, not yet started, set up as every child Commander runs is.
    """
    process = QProcess(parent)
    environment = QProcessEnvironment.systemEnvironment()
    for name, value in CHILD_ENVIRONMENT.items():
        environment.insert(name, value)
    process.setProcessEnvironment(environment)
    process.setWorkingDirectory(working_dir)
    return process
