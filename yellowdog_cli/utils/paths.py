"""
Path helpers with no dependencies beyond the standard library (and
settings.py's names), so that anything -- the configuration loader at
import, Commander -- can use them.
"""

import os
from os.path import abspath, expanduser, isfile, join, relpath

from yellowdog_cli.utils.settings import (
    CONFIG_FILE_NAME,
    USER_CONFIG_DIRECTORY,
    XDG_CONFIG_HOME,
)


def relative_if_possible(path: str) -> str:
    """
    The path relative to the current directory, which reads better in the
    messages that name it; or, where there is no relative path to it -- on
    Windows, a file on another drive, where relpath() raises ValueError --
    the absolute path, which still names it correctly from anywhere.
    """
    try:
        return relpath(path)
    except ValueError:
        return abspath(path)


def user_config_file() -> str:
    """
    The user's own configuration file, whether or not it exists.
    """
    base = os.environ.get(XDG_CONFIG_HOME) or join(expanduser("~"), ".config")
    return join(base, USER_CONFIG_DIRECTORY, CONFIG_FILE_NAME)


def default_config_file() -> str:
    """
    The configuration file read when '--config' names none: config.toml in
    the current directory, else the user's own if there is one, else
    config.toml, which does not exist.
    """
    if isfile(CONFIG_FILE_NAME):
        return CONFIG_FILE_NAME
    user_file = user_config_file()
    return user_file if isfile(user_file) else CONFIG_FILE_NAME


def is_user_config_file(path: str) -> bool:
    """
    Whether 'path' is the user's own configuration file.
    """
    return abspath(path) == abspath(user_config_file())
