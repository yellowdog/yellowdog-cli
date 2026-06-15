"""
Validate property dictionaries.
"""

from dataclasses import dataclass

from yellowdog_cli.utils.printing import print_error
from yellowdog_cli.utils.property_names import *


def validate_properties(data: dict, context: str):
    """
    Check that all keys in the supplied dictionary are found in the
    ALL_KEYS list. Raise an exception if not.
    """
    invalid_keys = set(_get_keys(data)) - set(ALL_KEYS)
    if invalid_keys:
        raise KeyError(f"Invalid properties in {context}: {invalid_keys}")


@dataclass
class DeprecatedKey:
    old_key: str
    new_key: str


DEPRECATED_KEYS = [
    DeprecatedKey("autoShutdown", f"Set {IDLE_POOL_TIMEOUT} to zero"),
    DeprecatedKey("autoShutdownDelay", IDLE_POOL_TIMEOUT),
    DeprecatedKey("nodeBootTimeLimit", NODE_BOOT_TIMEOUT),
    DeprecatedKey("nodeIdleTimeLimit", IDLE_NODE_TIMEOUT),
    DeprecatedKey("idleNodeShutdownEnabled", f"{IDLE_NODE_TIMEOUT} = 0"),
    DeprecatedKey("idlePoolShutdownEnabled", f"{IDLE_POOL_TIMEOUT} = 0"),
    DeprecatedKey("idleNodeShutdownTimeout", IDLE_NODE_TIMEOUT),
    DeprecatedKey("idlePoolShutdownTimeout", IDLE_POOL_TIMEOUT),
]

EXCLUDED_KEYS = [ENV, VARIABLES, INSTANCE_TAGS, TASK_DATA_INPUTS, TASK_DATA_OUTPUTS]


def _get_keys(data: dict | list) -> list[str]:
    """
    Recursively walk a dictionary or list collecting keys.
    Exclude dictionaries with user-specified keys.
    Raise an error for deprecated keys.
    """
    keys: list[str] = []

    if isinstance(data, dict):
        errors = False
        for key, value in data.items():
            for d_key in DEPRECATED_KEYS:
                if key == d_key.old_key:
                    print_error(
                        f"Property '{d_key.old_key}' is no longer"
                        f" supported; please replace with '{d_key.new_key}'"
                    )
                    errors = True
            keys.append(key)

            if isinstance(value, (dict, list)) and key not in EXCLUDED_KEYS:
                keys += _get_keys(value)

        if errors:
            raise ValueError("Please update your property names")

    elif isinstance(data, list):
        for element in data:
            if isinstance(element, dict):
                keys += _get_keys(element)

    return keys
