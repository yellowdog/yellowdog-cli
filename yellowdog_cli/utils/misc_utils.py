"""
General utility functions.
"""

import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from os.path import join, normpath, relpath
from typing import TypeAlias
from urllib.parse import urlparse

from dotenv import dotenv_values, find_dotenv, load_dotenv
from yellowdog_client.model import (
    ComputeRequirement,
    ConfiguredWorkerPool,
    ProvisionedWorkerPool,
    WorkRequirement,
)

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import print_info
from yellowdog_cli.utils.settings import YD_ENV_OVERRIDE

UTCNOW = datetime.now(timezone.utc)


def pathname_relative_to_config_file(config_file_dir: str, file: str) -> str:
    """
    Find the pathname of a file relative to the location
    of the config file
    """
    return normpath(relpath(join(config_file_dir, file)))


def generate_id(prefix: str = "", max_length: int = 60) -> str:
    """
    Add a UTC timestamp and check length.
    """
    # Include seconds to three decimal points
    generated_id = prefix + UTCNOW.strftime("_%y%m%d-%H%M%S%f")[:-3]
    if len(generated_id) > max_length:
        raise ValueError(
            f"Error: Generated ID '{generated_id}' would exceed "
            f"maximum length ({max_length})"
        )
    return generated_id


# Utility functions for creating links to YD entities
_EntityType: TypeAlias = (
    ConfiguredWorkerPool | ProvisionedWorkerPool | WorkRequirement | ComputeRequirement
)

entities: dict[str, str] = {
    "ConfiguredWorkerPool": "workers",
    "ProvisionedWorkerPool": "workers",
    "WorkRequirement": "work",
    "ComputeRequirement": "compute",
}


def link_entity(base_url: str, entity: _EntityType) -> str:
    entity_type_name = type(entity).__name__
    return link(
        base_url,
        f"#/{entities.get(entity_type_name)}/{entity.id}",  # type: ignore[union-attr]
        camel_case_split(entity_type_name).upper(),
    )


def link(base_url: str, url_suffix: str = "", text: str | None = None) -> str:
    url_parts = urlparse(base_url)
    netloc = url_parts.netloc.replace("api", "portal")
    base_url = url_parts.scheme + "://" + netloc
    url = base_url + "/" + url_suffix
    if not text:
        text = url
    if text == url:
        return url
    else:
        return f"{text} ({url})"


def camel_case_split(value: str) -> str:
    return " ".join(re.findall(r"[A-Z](?:[a-z]+|[A-Z]*(?=[A-Z]|$))", value))


def add_batch_number_postfix(name: str, batch_number: int, num_batches: int) -> str:
    """
    Generate a name using batch details.
    """
    if num_batches > 1:
        name += "_" + str(batch_number + 1).zfill(len(str(num_batches)))
    return name


#
# Functions for handling delimited variables within strings.
#
@dataclass(order=True)
class Substring:
    start: int
    end: int


def get_delimited_string_boundaries(
    input_string: str,
    opening_delimiter: str,
    closing_delimiter: str,
) -> list[Substring]:
    """
    Given an input string and a pair of opening and closing delimiter strings,
    find the list of start and end indices for the top-level strings enclosed
    by the opening and closing delimiters.

    For example:
        if input_string = "abc {{{{x}}_hello}} 234 {{{{world}}}}",
        and opening_delimiter = "{{", closing_delimiter = "}}",
        the function will return Substring objects: [(4, 19), (24, 37)]

    Opening and closing delimiters must be balanced across the entire
    input_string, otherwise an exception will be raised.
    """
    openings = [(x.span()[0], 1) for x in re.finditer(opening_delimiter, input_string)]
    closings = [(x.span()[0], -1) for x in re.finditer(closing_delimiter, input_string)]

    mismatched_delimiters_exception = ValueError(
        f"Mismatched variable delimiters ('{opening_delimiter}', '{closing_delimiter}')"
        f" in '{input_string}'"
    )

    if len(openings) != len(closings):
        raise mismatched_delimiters_exception

    slate = 0
    start = None
    substrings: list[Substring] = []

    for boundary in sorted(openings + closings):
        slate += boundary[1]
        if slate < 0:
            raise mismatched_delimiters_exception
        if slate == 1 and start is None:
            start = boundary[0]
        elif slate == 0:
            assert start is not None  # set when slate first reached 1
            substrings.append(
                Substring(start=start, end=boundary[0] + len(closing_delimiter))
            )
            start = None

    if slate > 0:
        raise mismatched_delimiters_exception

    return substrings


def split_delimited_string(
    s: str, opening_delimiter: str, closing_delimiter: str
) -> list[str]:
    """
    This function takes a string containing delimited sections and breaks it
    into a list of strings, including the non-delimited sections.
    Delimiters are retained.

    For example:
      when called with ("one{{two}}three{{{{four}}}}five", "{{", "}}")
      the result is: ['one', '{{two}}', 'three', '{{{{four}}}}', 'five']
    """

    # Get delimited boundaries
    delimited_boundaries: list[Substring] = get_delimited_string_boundaries(
        s, opening_delimiter, closing_delimiter
    )

    if not delimited_boundaries:
        return [s]

    # Get non-delimited boundaries (i.e., the gaps)
    non_delimited_boundaries: list[Substring] = []
    if delimited_boundaries[0].start > 0:  # Non-variable text at start?
        non_delimited_boundaries.insert(
            0, Substring(start=0, end=delimited_boundaries[0].start)
        )
    for index in range(len(delimited_boundaries) - 1):
        non_delimited_boundaries.insert(
            index + 1,
            (
                Substring(
                    start=delimited_boundaries[index].end,
                    end=delimited_boundaries[index + 1].start,
                )
            ),
        )
    # Non-variable text at end?
    final_boundary: int = delimited_boundaries[len(delimited_boundaries) - 1].end
    if len(s) > final_boundary:
        non_delimited_boundaries.append(Substring(start=final_boundary, end=len(s)))

    return [
        s[boundary.start : boundary.end]
        for boundary in sorted(non_delimited_boundaries + delimited_boundaries)  # type: ignore[type-var]
    ]


def remove_outer_delimiters(
    input_string: str, opening_delimiter: str, closing_delimiter: str
) -> str:
    """
    Remove the outermost delimiters from a string.
    There is no checking for a well-formed string.
    """
    # The string and the closing delimiter must be reversed ([::-1]) for
    # removal, then re-reversed
    return input_string.replace(f"{opening_delimiter}", "", 1)[::-1].replace(
        f"{closing_delimiter[::-1]}", "", 1
    )[::-1]


def format_yd_name(yd_name: str, add_prefix: bool = True) -> str:
    """
    Format a string to be consistent with YellowDog naming requirements.
    """
    # Make obvious substitutions
    new_yd_name = yd_name.replace("/", "-").replace(" ", "_").replace(".", "_").lower()

    # Enforce acceptable regex
    new_yd_name = re.sub("[^a-z0-9_-]", "", new_yd_name)

    # Must start with an alphabetic character
    if add_prefix and not new_yd_name[0].isalpha():
        new_yd_name = f"y{new_yd_name}"

    # Mustn't exceed 60 chars
    return new_yd_name[:60]


def load_dotenv_file():
    """
    Load extra environment variables from a .env file if it exists.
    Do not override existing variables (environment takes precedence)
    unless --env-override is set or YD_ENV_OVERRIDE is set in the environment.
    Report on YD vars that are taken from .env.
    """
    dotenv_file = find_dotenv(usecwd=True)
    if dotenv_file == "":
        return

    env_override = bool(ARGS_PARSER.env_override) or bool(
        os.environ.get(YD_ENV_OVERRIDE)
    )

    print_info(
        f"Loading environment variables from '{dotenv_file}' ("
        f"{'OVERRIDING' if env_override else 'NOT OVERRIDING'} existing variables)"
    )

    dotenv_yd_substitutions = [  # Find 'YD' variables
        f"'{key}'"
        for key in dotenv_values(dotenv_file)
        if key.startswith("YD") and (os.environ.get(key) is None or env_override)
    ]

    if dotenv_yd_substitutions:
        print_info(
            f"Adding 'YD' environment variable(s): {', '.join(dotenv_yd_substitutions)}"
        )

    # Actually load the variables (including non-'YD' variables)
    load_dotenv(dotenv_file, override=env_override)
