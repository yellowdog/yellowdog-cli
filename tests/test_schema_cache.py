"""
The compiled validator cache (yellowdog_cli/utils/schema_cache.py): a
validator is stored on a miss and loaded on a hit, the same validator either
way; a changed schema misses, and the stem keeps its CACHE_KEEP most
recently used files, so two environments sharing the cache do not delete
each other's; a directory
that cannot be trusted, and a file that cannot be read, fall back to
compiling, and say why to the registered reporter (print_debug(), under
'--debug', in a real command), once per reason.
"""

import copy
import marshal
import os
import subprocess
import sys

import fastjsonschema
import pytest

from yellowdog_cli.utils import schema_cache
from yellowdog_cli.utils.schema_cache import (
    CACHE_DIRECTORY_NAME,
    CACHE_KEEP,
    CACHE_SUFFIX,
    REPORT_PREFIX,
    cache_directory,
    compile_validator,
    report_problems_to,
)
from yellowdog_cli.utils.spec_schema import Family, build_schema

SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "$id": "https://example.com/thing.schema.json",
    "type": "object",
    "properties": {"n": {"type": "integer"}, "s": {"$ref": "#/$defs/s"}},
    "additionalProperties": False,
    "$defs": {"s": {"type": "string", "pattern": "^a"}},
}

POSIX_ONLY = pytest.mark.skipif(
    sys.platform == "win32", reason="POSIX directory permissions"
)


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(schema_cache, "_temp_root", lambda: tmp_path)
    return tmp_path


@pytest.fixture()
def reported() -> list[str]:
    messages: list[str] = []
    report_problems_to(messages.append)
    return messages


def _files(root, stem="thing"):
    directory = cache_directory()
    assert directory is not None
    return sorted(
        p.name
        for p in directory.iterdir()
        if p.suffix == CACHE_SUFFIX and p.stem.rsplit("-", 1)[0] == stem
    )


def _compile(schema=SCHEMA, stem="thing"):
    return compile_validator(copy.deepcopy(schema), stem)


def _no_compiling(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("compiled despite a cached validator")

    monkeypatch.setattr(fastjsonschema, "compile_to_code", refuse)


def _failure(validate, document) -> fastjsonschema.JsonSchemaValueException:
    with pytest.raises(fastjsonschema.JsonSchemaValueException) as info:
        validate(document)
    return info.value


class TestHitAndMiss:
    def test_a_miss_stores_one_file(self, root):
        _compile()
        assert len(_files(root)) == 1

    def test_neither_a_miss_nor_a_hit_is_reported(self, root, reported):
        _compile()
        _compile()
        assert reported == []

    def test_a_hit_compiles_nothing(self, root, monkeypatch):
        _compile()
        _no_compiling(monkeypatch)
        validate = _compile()
        validate({"n": 1, "s": "abc"})
        assert _failure(validate, {"s": "b"}).message == "data.s must match pattern ^a"

    def test_the_cached_validator_fails_as_fastjsonschemas_own(self, root):
        _compile()
        cached = _compile()
        direct = fastjsonschema.compile(copy.deepcopy(SCHEMA))
        for document in ({"n": "x"}, {"s": "b"}, {"nope": 1}, []):
            ours, theirs = _failure(cached, document), _failure(direct, document)
            assert (ours.message, ours.name, ours.rule, ours.definition) == (
                theirs.message,
                theirs.name,
                theirs.rule,
                theirs.definition,
            )

    def test_a_real_family_round_trips(self, root, monkeypatch):
        compile_validator(build_schema(Family.NODE_ACTIONS), "node-actions")
        _no_compiling(monkeypatch)
        validate = compile_validator(build_schema(Family.NODE_ACTIONS), "node-actions")
        monkeypatch.undo()
        direct = fastjsonschema.compile(build_schema(Family.NODE_ACTIONS))
        for document in ({"nodeActions": []}, {"nope": 1}, []):
            assert _failure(validate, document).message == (
                _failure(direct, document).message
            )


class TestInvalidation:
    @staticmethod
    def _variant(minimum: int) -> dict:
        changed = copy.deepcopy(SCHEMA)
        changed["properties"]["n"]["minimum"] = minimum
        return changed

    def test_a_changed_schema_is_a_second_file_not_a_replacement(self, root):
        # Two environments building different schemas each keep theirs
        _compile()
        (before,) = _files(root)
        _compile(self._variant(0))
        files = _files(root)
        assert len(files) == 2 and before in files

    def test_only_the_most_recently_used_are_kept(self, root):
        _compile()
        (first,) = _files(root)
        for minimum in range(CACHE_KEEP):
            # The first, long unused, is the oldest whatever the clock's grain
            os.utime(cache_directory() / first, (1, 1))  # type: ignore[operator]
            _compile(self._variant(minimum))
        files = _files(root)
        assert len(files) == CACHE_KEEP
        assert first not in files

    def test_a_file_used_is_kept_ahead_of_older_ones(self, root):
        _compile()
        (first,) = _files(root)
        directory = cache_directory()
        assert directory is not None
        for minimum in range(CACHE_KEEP - 1):
            _compile(self._variant(minimum))
        for name in _files(root):
            os.utime(directory / name, (1, 1))  # All long unused...
        _compile()  # ...but the first, loaded now
        _compile(self._variant(99))  # One too many: the oldest goes
        assert first in _files(root)
        assert len(_files(root)) == CACHE_KEEP

    def test_another_stem_is_left_alone(self, root):
        _compile(stem="config-common")
        _compile(stem="config-common-workerPool")
        for minimum in range(CACHE_KEEP + 1):
            _compile(self._variant(minimum), stem="config-common")
        assert len(_files(root, "config-common")) == CACHE_KEEP
        assert len(_files(root, "config-common-workerPool")) == 1

    def test_cached_code_that_fails_as_it_loads_is_recompiled(self, root, reported):
        _compile()
        (name,) = _files(root)
        path = cache_directory() / name  # type: ignore[operator]
        path.write_bytes(marshal.dumps(compile("raise OSError('x')", "<x>", "exec")))
        _failure(_compile(), {"n": "x"})
        assert reported == [
            f"{REPORT_PREFIX}'{path}' failed as it loaded (x); recompiling"
        ]

    def test_a_corrupt_file_is_recompiled_and_replaced(self, root, reported):
        _compile()
        (name,) = _files(root)
        path = cache_directory() / name  # type: ignore[operator]
        path.write_bytes(b"not marshalled code")
        _compile()({"n": 1})
        assert path.read_bytes() != b"not marshalled code"
        assert reported == [
            f"{REPORT_PREFIX}'{path}' is not a compiled schema; recompiling"
        ]

    def test_a_file_defining_no_validator_is_recompiled(self, root, reported):
        _compile()
        (name,) = _files(root)
        path = cache_directory() / name  # type: ignore[operator]
        path.write_bytes(marshal.dumps(compile("x = 1", "<x>", "exec")))
        _failure(_compile(), {"n": "x"})
        assert reported == [
            f"{REPORT_PREFIX}'{path}' defines no validator; recompiling"
        ]


@POSIX_ONLY
class TestTrust:
    def test_the_directory_is_the_users_own(self, root):
        directory = cache_directory()
        assert directory is not None
        assert directory.name.endswith(f"-{os.getuid()}")
        assert directory.stat().st_mode & 0o777 == 0o700

    def test_a_directory_open_to_others_is_not_used(self, root, reported):
        directory = cache_directory()
        assert directory is not None
        directory.chmod(0o777)
        assert cache_directory() is None
        _compile()({"n": 1})
        assert not any(directory.iterdir())
        assert reported == [
            f"{REPORT_PREFIX}'{directory}' is open to other users (mode 777);"
            " compiling the schemas without it"
        ]

    def test_a_symlinked_directory_is_not_used(self, root, tmp_path_factory, reported):
        elsewhere = tmp_path_factory.mktemp("elsewhere")
        elsewhere.chmod(0o700)
        link = root / f"{CACHE_DIRECTORY_NAME}-{os.getuid()}"
        link.symlink_to(elsewhere)
        assert cache_directory() is None
        _compile()({"n": 1})
        assert not any(elsewhere.iterdir())
        assert reported == [
            f"{REPORT_PREFIX}'{link}' is a symbolic link;"
            " compiling the schemas without it"
        ]

    def test_no_directory_still_compiles(self, root, monkeypatch, reported):
        missing = root / "missing" / "x"
        monkeypatch.setattr(schema_cache, "_temp_root", lambda: missing)
        assert cache_directory() is None
        _failure(_compile(), {"n": "x"})
        (message,) = reported
        assert message.startswith(f"{REPORT_PREFIX}cannot create '{missing}/")
        assert message.endswith("; compiling the schemas without it")

    @pytest.mark.skipif(
        sys.platform != "win32" and os.geteuid() == 0,
        reason="root writes regardless of permissions",
    )
    def test_an_unwritable_directory_is_reported(self, root, reported):
        directory = cache_directory()
        assert directory is not None
        directory.chmod(0o500)
        try:
            _compile()({"n": 1})
        finally:
            directory.chmod(0o700)
        (message,) = reported
        assert message.startswith(f"{REPORT_PREFIX}cannot write to '{directory}': ")

    def test_a_reason_is_reported_once(self, root, reported):
        directory = cache_directory()
        assert directory is not None
        directory.chmod(0o777)
        _compile()
        _compile(stem="other")
        assert len(reported) == 1

    def test_nothing_is_reported_without_a_reporter(self, root):
        directory = cache_directory()
        assert directory is not None
        directory.chmod(0o777)
        _compile()({"n": 1})  # and nothing raised


@POSIX_ONLY
class TestThroughACommand:
    """
    A real command, with its temporary directory (TMPDIR) holding a cache
    directory open to others: '--debug' says why the cache is not used,
    and without it nothing is said.
    """

    def _run(self, tmp_path, *options):
        (tmp_path / "config.toml").write_text(
            '[common]\nnamespace = "ns"\ntag = "tag"\n'
        )
        temp = tmp_path / "temp"
        cache = temp / f"{CACHE_DIRECTORY_NAME}-{os.getuid()}"
        cache.mkdir(parents=True)
        cache.chmod(0o777)
        env = {k: v for k, v in os.environ.items() if not k.startswith("YD_")}
        env.update({"YD_KEY": "a-key", "YD_SECRET": "a-secret", "TMPDIR": str(temp)})
        result = subprocess.run(
            ["yd-variables", "--nf", *options, "namespace"],
            capture_output=True,
            text=True,
            env=env,
            cwd=tmp_path,
            timeout=120,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout + result.stderr, cache

    def test_debug_says_why(self, tmp_path):
        output, cache = self._run(tmp_path, "--debug")
        assert f"{REPORT_PREFIX}'{cache}' is open to other users" in output

    def test_nothing_is_said_without_debug(self, tmp_path):
        output, _ = self._run(tmp_path)
        assert REPORT_PREFIX not in output
