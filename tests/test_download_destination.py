"""
Tests for where 'yd-download' puts each item locally.

This is the regression these guard: Commander used to pass one glob with
'--destination', which the glob transfer expands per match under the destination
by name. Passing several literal paths with '--destination' instead took the other
branch, copying each item's *contents* into the destination and losing its own
directory level. '--into' names that container behaviour explicitly.
"""

from pathlib import Path

from cli_test_helpers import shell

from yellowdog_cli.download import local_destination_for

# --- '--into': a container, each item keeps its name --------------------------


def test_into_places_a_literal_item_under_its_own_name():
    assert local_destination_for("pyex-logs", into_dir="results") == Path(
        "results/pyex-logs"
    )


def test_into_uses_the_basename_of_a_resolved_absolute_path():
    # Commander passes resolved paths, which is what made the regression visible.
    assert local_destination_for("S3:bucket/pfx/pyex-logs", into_dir="results") == Path(
        "results/pyex-logs"
    )


def test_into_ignores_a_trailing_slash():
    assert local_destination_for(
        "S3:bucket/pfx/pyex-logs/", into_dir="results"
    ) == Path("results/pyex-logs")


def test_into_takes_the_directory_unchanged_for_a_pattern():
    # The glob transfer already places every match under the destination by its
    # own name, so appending the pattern would create a dir named 'pyex*'.
    for pattern in ("pyex*", "pyex?", "pyex[0-9]"):
        assert local_destination_for(pattern, into_dir="results") == Path("results")


def test_several_items_get_separate_directories():
    # The actual bug: with --destination these all collapsed into 'results'.
    names = ["pyex-001", "pyex-logs", "pyex-results"]
    assert [local_destination_for(n, into_dir="results") for n in names] == [
        Path("results/pyex-001"),
        Path("results/pyex-logs"),
        Path("results/pyex-results"),
    ]


# --- '--destination' and the default are unchanged ---------------------------


def test_destination_still_names_the_path_corresponding_to_the_item():
    assert local_destination_for("pyex-logs", explicit_destination="results") == Path(
        "results"
    )


def test_destination_still_wins_for_a_pattern():
    assert local_destination_for("pyex*", explicit_destination="results") == Path(
        "results"
    )


def test_no_destination_mirrors_the_remote_name():
    assert local_destination_for("S3:bucket/pfx/mydir") == Path("mydir")


def test_no_destination_expands_a_pattern_into_the_current_directory():
    assert local_destination_for("pyex*") == Path(".")


# --- The two options are mutually exclusive ----------------------------------


def test_destination_and_into_together_are_refused():
    # They answer different questions; honouring both is meaningless.
    result = shell("yd-download somepath --destination out --into out")
    assert result.exit_code == 2
    assert "not allowed with argument" in (result.stderr + result.stdout)
