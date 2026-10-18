"""
Tests for where 'yd-download' puts each item locally.

With '--destination', a glob is expanded per match under the destination by
name, but several literal paths take the other branch, copying each item's
*contents* into the destination and losing its own directory level. '--into'
names the container behaviour explicitly, so each literal item, as Commander
passes them, keeps its own directory.
"""

from pathlib import Path

from cli_test_helpers import shell

from yellowdog_cli.download import destination_is_item, local_destination_for

# --- '--into': a container, each item keeps its name --------------------------


def test_into_places_a_literal_item_under_its_own_name():
    assert local_destination_for("pyex-logs", into_dir="results") == Path(
        "results/pyex-logs"
    )


def test_into_uses_the_basename_of_a_resolved_absolute_path():
    # Commander passes resolved paths, so this is the case it depends on.
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
    # The point of '--into': with --destination these would all collapse into
    # 'results'.
    names = ["pyex-001", "pyex-logs", "pyex-results"]
    assert [local_destination_for(n, into_dir="results") for n in names] == [
        Path("results/pyex-001"),
        Path("results/pyex-logs"),
        Path("results/pyex-results"),
    ]


# --- '--destination' and the default ------------------------------------------


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


def test_an_item_at_the_remotes_root_is_named_without_the_remote():
    # 'loc:a.txt' has no '/' to split on: '--into' must not write
    # 'results/loc:a.txt'
    assert local_destination_for(
        "loc:a.txt", into_dir="results", names_remote=True
    ) == Path("results/a.txt")
    assert local_destination_for("loc:a.txt", names_remote=True) == Path("a.txt")


def test_a_colon_in_the_items_own_name_is_kept():
    assert local_destination_for(
        "S3:bucket/a:b.txt", into_dir="results", names_remote=True
    ) == Path("results/a:b.txt")
    assert local_destination_for("a:b.txt", into_dir="results") == Path(
        "results/a:b.txt"
    )


def test_no_destination_expands_a_pattern_into_the_current_directory():
    assert local_destination_for("pyex*") == Path(".")


# --- Whether the destination is the item's own path --------------------------


def test_into_and_the_default_give_a_literal_item_its_own_path():
    # So a single file is transferred to that path, not into a directory there
    assert destination_is_item("a.txt", into_dir="results")
    assert destination_is_item("S3:bucket/pfx/a.txt")


def test_destination_is_a_directory_to_copy_into():
    assert not destination_is_item("a.txt", explicit_destination="results")


def test_a_pattern_never_names_an_item():
    assert not destination_is_item("pyex*", into_dir="results")
    assert not destination_is_item("pyex*")
    assert not destination_is_item("pyex*", explicit_destination="results")


# --- The two options are mutually exclusive ----------------------------------


def test_destination_and_into_together_are_refused():
    # They answer different questions; honouring both is meaningless.
    result = shell("yd-download somepath --destination out --into out")
    assert result.exit_code == 2
    assert "not allowed with argument" in (result.stderr + result.stdout)
