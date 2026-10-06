"""
Unit tests for yellowdog_cli.utils.csv_data

Tests focus on pure functions and the CSVTaskData / CSVDataCache classes.
Functions that require API calls or full Work Requirement pipelines are
out of scope for unit tests.
"""

from unittest.mock import MagicMock

import pytest

import yellowdog_cli.utils.csv_data as csv_module
from yellowdog_cli.utils.config_types import ConfigWorkRequirement
from yellowdog_cli.utils.csv_data import (
    CSVDataCache,
    CSVTaskData,
    csv_expand_toml_tasks,
    csv_variables_substitution,
    get_csv_file_index,
    substitutions_present,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def simple_csv(tmp_path):
    """
    A CSV file with header row and two data rows.
    """
    csv_file = tmp_path / "tasks.csv"
    csv_file.write_text("name,value\njob_a,10\njob_b,20\n")
    return str(csv_file)


@pytest.fixture()
def single_row_csv(tmp_path):
    """
    A CSV file with header and one data row.
    """
    csv_file = tmp_path / "single.csv"
    csv_file.write_text("x,y\n1,2\n")
    return str(csv_file)


# ---------------------------------------------------------------------------
# csv_variables_substitution
# ---------------------------------------------------------------------------


def _sub(prototype, **row):
    return csv_variables_substitution(
        prototype, list(row), list(row.values()), where="'tasks.csv' row 2"
    )


class TestCsvVariablesSubstitution:
    """
    A CSV row is substituted into the prototype Task's data, string by
    string, never into its text: a value is only ever a value.
    """

    def test_plain_substitution(self):
        assert _sub({"a": "Hello <<name>>"}, name="World") == {"a": "Hello World"}

    def test_other_text_unchanged(self):
        prototype = {"a": "<<other>> {{x}} <<num:other>>"}
        assert _sub(prototype, name="World") == prototype

    def test_multiple_occurrences(self):
        assert _sub({"a": "<<x>> and <<x>>"}, x="val") == {"a": "val and val"}

    @pytest.mark.parametrize(
        "value",
        ["it's", r"C:\temp\new", "v', 'injected': 'yes", 'say "hi"', "<<y>>"],
        ids=["apostrophe", "backslashes", "would-be-key", "quotes", "a-reference"],
    )
    def test_value_is_only_ever_a_value(self, value):
        assert _sub({"a": "<<x>>"}, x=value, y="Y") == {"a": value}

    def test_property_names_are_substituted(self):
        prototype = {"environment": {"<<k>>": "<<v>>", "FIXED": "1"}}
        assert _sub(prototype, k="KEY", v="value") == {
            "environment": {"KEY": "value", "FIXED": "1"}
        }

    def test_other_values_and_lists(self):
        prototype = {
            "n": 5,
            "flag": True,
            "none": None,
            "args": ["<<x>>", 3, ["<<x>>"]],
        }
        assert _sub(prototype, x="a") == {
            "n": 5,
            "flag": True,
            "none": None,
            "args": ["a", 3, ["a"]],
        }

    def test_prototype_is_not_changed(self):
        prototype = {"args": ["<<x>>"]}
        _sub(prototype, x="a")
        assert prototype == {"args": ["<<x>>"]}

    @pytest.mark.parametrize(
        "text,value,expected",
        [
            ("<<num:x>>", "7", 7),
            ("<<num:x>>", "2.5", 2.5),
            ("<<num:x>>", "1.10", 1.1),
            ("<<num:x>>", "1e3", 1000.0),
            ("<<bool:x>>", "TRUE", True),
            ("<<bool:x>>", "false ", False),
            ("<<array:x>>", '["a", 1]', ["a", 1]),
            ("<<array:x>>", "['a', True]", ["a", True]),
            ("<<table:x>>", '{"k": "v"}', {"k": "v"}),
            ("<<format_name:x>>", "My Job/Run", "my_job-run"),
        ],
    )
    def test_typed_whole_value(self, text, value, expected):
        assert _sub({"a": text}, x=value) == {"a": expected}

    @pytest.mark.parametrize(
        "text,value,expected",
        [
            ("n-<<num:x>>", "1.10", "n-1.10"),
            ("f=<<bool:x>>", "True", "f=true"),
            ("--tags=<<array:x>>", "['a', 'b']", '--tags=["a", "b"]'),
            ("task-<<format_name:x>>-end", "Test Case", "task-test_case-end"),
        ],
    )
    def test_typed_within_a_longer_string(self, text, value, expected):
        assert _sub({"a": text}, x=value) == {"a": expected}

    @pytest.mark.parametrize(
        "text,value,reason",
        [
            ("<<num:count>>", "abc", "'abc' is not a number"),
            ("<<num:count>>", "nan", "is not a finite number"),
            ("n-<<num:count>>", "abc", "'abc' is not a number"),
            ("<<bool:count>>", "yes", "'yes' is not true or false"),
            ("<<array:count>>", "1, 2", "it is a tuple"),
        ],
    )
    def test_invalid_value_names_file_row_and_column(self, text, value, reason):
        with pytest.raises(ValueError) as raised:
            _sub({"a": text}, count=value)
        message = str(raised.value)
        assert message.startswith("'tasks.csv' row 2, column 'count': ")
        assert reason in message


# ---------------------------------------------------------------------------
# substitutions_present
# ---------------------------------------------------------------------------


class TestSubstitutionsPresent:
    @pytest.mark.parametrize(
        "var_names,prototype,expected",
        [
            (["myvar"], "some <<myvar>> text", True),
            (["myvar"], "no substitutions here", False),
            (["count"], "'<<num:count>>'", True),
            (["flag"], "'<<bool:flag>>'", True),
            (["label"], "<<format_name:label>>", True),
            (["tags"], "<<array:tags>>", True),
            (["env"], {"a": ["x", {"<<env>>": 1}]}, True),
            (["env"], {"a": ["<<other>>"], "n": 5}, False),
            (["a", "b", "c"], "only <<b>> here", True),
            (["x", "y"], "<<z>> is not in the list", False),
            ([], "<<anything>>", False),
            (["myvar"], "", False),
        ],
    )
    def test_substitutions_present(self, var_names, prototype, expected):
        assert substitutions_present(var_names, prototype) is expected


# ---------------------------------------------------------------------------
# get_csv_file_index
# ---------------------------------------------------------------------------


class TestGetCsvFileIndex:
    def test_no_index_suffix(self):
        task_groups = [{}, {}]
        filename, index = csv_module.get_csv_file_index("myfile.csv", task_groups)
        assert filename == "myfile.csv"
        assert index is None

    def test_numeric_suffix_first_group(self):
        task_groups = [{}, {}]
        filename, index = csv_module.get_csv_file_index("myfile.csv:1", task_groups)
        assert filename == "myfile.csv"
        assert index == 0  # 1-based → 0-based

    def test_numeric_suffix_second_group(self):
        task_groups = [{}, {}, {}]
        filename, index = csv_module.get_csv_file_index("myfile.csv:2", task_groups)
        assert filename == "myfile.csv"
        assert index == 1

    def test_numeric_suffix_out_of_range_raises(self):
        task_groups = [{}]
        with pytest.raises(Exception, match="outside Task Group range"):
            csv_module.get_csv_file_index("myfile.csv:5", task_groups)

    def test_numeric_suffix_zero_raises(self):
        task_groups = [{}, {}]
        with pytest.raises(Exception, match="outside Task Group range"):
            csv_module.get_csv_file_index("myfile.csv:0", task_groups)

    def test_name_suffix_matches_task_group(self):
        task_groups = [{"name": "group-a"}, {"name": "group-b"}]
        filename, index = csv_module.get_csv_file_index(
            "myfile.csv:group-b", task_groups
        )
        assert filename == "myfile.csv"
        assert index == 1

    def test_name_suffix_no_match_raises(self):
        task_groups = [{"name": "group-a"}]
        with pytest.raises(ValueError, match=r"No matches.*named 'group-a'"):
            csv_module.get_csv_file_index("myfile.csv:no-such-group", task_groups)


class TestOneCsvFilePerTaskGroup:
    """
    A Task Group is given at most one CSV file, whether by position, number
    or name, and two for one are refused naming both.
    """

    @pytest.fixture
    def files(self, tmp_path, monkeypatch):
        (tmp_path / "d.csv").write_text("a\n1\n", encoding="utf-8")
        (tmp_path / "wr.json").write_text(
            '{"taskGroups": [{"name": "one", "tasks": [{"arguments": ["<<a>>"]}]},'
            ' {"name": "two", "tasks": [{"arguments": ["<<a>>"]}]}]}',
            encoding="utf-8",
        )
        return tmp_path

    @pytest.mark.parametrize(
        "suffixes", [("", ":1"), (":one", ":1"), (":2", ":two"), (":1", ":1")]
    )
    def test_two_files_for_one_task_group_are_refused(self, files, suffixes):
        csv_files = [str(files / "d.csv") + suffix for suffix in suffixes]
        with pytest.raises(ValueError, match="is given more than one CSV file"):
            csv_module.load_json_file_with_csv_task_expansion(
                str(files / "wr.json"), csv_files
            )

    def test_one_file_may_serve_two_task_groups(self, files):
        csv_file = str(files / "d.csv")
        wr = csv_module.load_json_file_with_csv_task_expansion(
            str(files / "wr.json"), [csv_file + ":1", csv_file + ":2"]
        )
        assert [len(tg["tasks"]) for tg in wr["taskGroups"]] == [1, 1]

    def test_a_task_group_without_tasks_is_reported(self, files):
        (files / "wr.json").write_text('{"taskGroups": [{}]}', encoding="utf-8")
        with pytest.raises(ValueError, match="needs a 'tasks' list"):
            csv_module.load_json_file_with_csv_task_expansion(
                str(files / "wr.json"), [str(files / "d.csv")]
            )

    def test_no_task_groups_is_reported(self, files):
        (files / "wr.json").write_text("{}", encoding="utf-8")
        with pytest.raises(ValueError, match="needs a 'taskGroups' list"):
            csv_module.load_json_file_with_csv_task_expansion(
                str(files / "wr.json"), [str(files / "d.csv")]
            )

    def test_invalid_json_names_the_file(self, files):
        (files / "wr.json").write_text("{nope", encoding="utf-8")
        with pytest.raises(ValueError, match="Invalid JSON in"):
            csv_module.load_json_file_with_csv_task_expansion(
                str(files / "wr.json"), [str(files / "d.csv")]
            )


# ---------------------------------------------------------------------------
# CSVTaskData
# ---------------------------------------------------------------------------


class TestCSVTaskData:
    def test_var_names(self, simple_csv):
        data = CSVTaskData(simple_csv)
        assert data.var_names == ["name", "value"]

    def test_total_tasks(self, simple_csv):
        data = CSVTaskData(simple_csv)
        assert data.total_tasks == 2

    def test_remaining_tasks_initially_equals_total(self, simple_csv):
        data = CSVTaskData(simple_csv)
        assert data.remaining_tasks == 2

    def test_iteration(self, simple_csv):
        data = CSVTaskData(simple_csv)
        rows = list(data)
        assert rows == [["job_a", "10"], ["job_b", "20"]]

    def test_remaining_tasks_decrements(self, simple_csv):
        data = CSVTaskData(simple_csv)
        next(data)
        assert data.remaining_tasks == 1
        next(data)
        assert data.remaining_tasks == 0

    def test_stop_iteration(self, simple_csv):
        data = CSVTaskData(simple_csv)
        list(data)  # exhaust
        with pytest.raises(StopIteration):
            next(data)

    def test_reset_allows_reiteration(self, simple_csv):
        data = CSVTaskData(simple_csv)
        first_pass = list(data)
        data.reset()
        second_pass = list(data)
        assert first_pass == second_pass

    def test_mismatched_row_lengths_raise(self, tmp_path):
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_text("a,b,c\n1,2,3\n4,5\n")  # row 3 has 2 cols instead of 3
        with pytest.raises(Exception, match="Malformed CSV"):
            CSVTaskData(str(bad_csv))

    def test_single_row(self, single_row_csv):
        data = CSVTaskData(single_row_csv)
        assert data.total_tasks == 1
        assert data.var_names == ["x", "y"]
        assert list(data) == [["1", "2"]]

    def test_headings_without_rows_are_refused(self, tmp_path):
        csv_file = tmp_path / "header_only.csv"
        csv_file.write_text("col1,col2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="headings but no data rows"):
            CSVTaskData(str(csv_file))

    def test_a_repeated_heading_is_refused(self, tmp_path):
        csv_file = tmp_path / "repeated.csv"
        csv_file.write_text("a,b,a\n1,2,3\n", encoding="utf-8")
        with pytest.raises(ValueError, match=r"repeats the heading.*'a'"):
            CSVTaskData(str(csv_file))

    def test_an_empty_heading_is_refused(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("a,,c\n1,2,3\n", encoding="utf-8")
        with pytest.raises(ValueError, match="empty heading \\(column 2\\)"):
            CSVTaskData(str(csv_file))


# ---------------------------------------------------------------------------
# CSVDataCache
# ---------------------------------------------------------------------------


class TestCSVFiles:
    def test_byte_order_mark_is_not_part_of_the_first_heading(self, tmp_path):
        # Excel's "CSV UTF-8" begins the file with one
        csv_file = tmp_path / "excel.csv"
        csv_file.write_bytes(b"\xef\xbb\xbfname,n\nalpha,1\n")
        assert CSVTaskData(str(csv_file)).var_names == ["name", "n"]

    def test_utf8_is_read_as_utf8(self, tmp_path):
        csv_file = tmp_path / "accents.csv"
        csv_file.write_bytes("name\ncaf\u00e9\n".encode())
        assert list(CSVTaskData(str(csv_file))) == [["caf\u00e9"]]

    def test_blank_lines_are_skipped(self, tmp_path):
        csv_file = tmp_path / "blank.csv"
        csv_file.write_text("name\na\n\nb\n")
        assert list(CSVTaskData(str(csv_file))) == [["a"], ["b"]]

    def test_quoted_line_break_is_kept(self, tmp_path):
        csv_file = tmp_path / "multiline.csv"
        csv_file.write_bytes(b'name,text\na,"one\r\ntwo"\n')
        assert list(CSVTaskData(str(csv_file))) == [["a", "one\r\ntwo"]]

    def test_empty_file_raises(self, tmp_path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        with pytest.raises(ValueError, match="is empty"):
            CSVTaskData(str(csv_file))

    def test_line_number_is_the_line_in_the_file(self, tmp_path):
        csv_file = tmp_path / "lines.csv"
        csv_file.write_text('name,text\na,"one\ntwo"\n\nb,x\n')
        data = CSVTaskData(str(csv_file))
        lines = []
        for _ in data:
            lines.append(data.line_number)
        assert lines == [3, 5]  # A quoted line break and a blank line before b


class TestWindowsPaths:
    @pytest.mark.parametrize(
        "name,expected",
        [
            (r"C:\data\tasks.csv", (r"C:\data\tasks.csv", None)),
            (r"C:\data\tasks.csv:2", (r"C:\data\tasks.csv", 1)),
            (r"C:\data\tasks.csv:group-b", (r"C:\data\tasks.csv", 1)),
        ],
    )
    def test_a_drive_letter_is_not_a_task_group(self, name, expected, monkeypatch):
        warning = MagicMock()
        monkeypatch.setattr(csv_module, "print_warning", warning)
        groups = [{"name": "group-a"}, {"name": "group-b"}]
        assert get_csv_file_index(name, groups) == expected
        warning.assert_not_called()

    def test_csv_without_a_specification_opens_the_whole_path(
        self, tmp_path, monkeypatch
    ):
        # The suffix is parsed once; the file is the path before it
        monkeypatch.setattr(csv_module, "print_info", MagicMock())
        opened = []
        real = csv_module.CSV_DATA_CACHE.get_csv_task_data

        def _get(filename):
            opened.append(filename)
            return real(str(tmp_path / "tasks.csv"))

        (tmp_path / "tasks.csv").write_text("x\na\n")
        monkeypatch.setattr(csv_module.CSV_DATA_CACHE, "get_csv_task_data", _get)
        wr = csv_expand_toml_tasks(
            ConfigWorkRequirement(task_type="<<x>>"), r"C:\data\tasks.csv:1"
        )
        assert opened[0] == r"C:\data\tasks.csv"
        assert wr["taskGroups"][0]["tasks"] == [{"taskType": "a"}]


class TestCSVDataCache:
    def test_cache_hit_resets_iterator(self, simple_csv):
        cache = CSVDataCache()
        data1 = cache.get_csv_task_data(simple_csv)
        list(data1)  # exhaust
        data2 = cache.get_csv_task_data(simple_csv)
        assert data2.remaining_tasks == 2  # reset was called

    def test_cache_miss_loads_file(self, simple_csv):
        cache = CSVDataCache()
        data = cache.get_csv_task_data(simple_csv)
        assert data.total_tasks == 2

    def test_max_entries_zero_disables_caching(self, simple_csv):
        cache = CSVDataCache(max_entries=0)
        data1 = cache.get_csv_task_data(simple_csv)
        data2 = cache.get_csv_task_data(simple_csv)
        # Different objects since caching is disabled
        assert data1 is not data2

    def test_max_entries_evicts_oldest(self, tmp_path):
        csv_a = tmp_path / "a.csv"
        csv_b = tmp_path / "b.csv"
        csv_c = tmp_path / "c.csv"
        for f in [csv_a, csv_b, csv_c]:
            f.write_text("col\nval\n")

        cache = CSVDataCache(max_entries=2)
        da = cache.get_csv_task_data(str(csv_a))
        cache.get_csv_task_data(str(csv_b))
        # Adding c should evict a
        cache.get_csv_task_data(str(csv_c))
        # a is no longer in cache; fetching it creates a new object
        da2 = cache.get_csv_task_data(str(csv_a))
        assert da is not da2

    def test_unlimited_cache_by_default(self, tmp_path):
        cache = CSVDataCache()
        files = []
        for i in range(5):
            f = tmp_path / f"file{i}.csv"
            f.write_text("col\nval\n")
            files.append(str(f))
        # Load all files
        objects = [cache.get_csv_task_data(f) for f in files]
        # Fetch again — should be same objects (cache hit)
        for i, f in enumerate(files):
            obj = cache.get_csv_task_data(f)
            assert obj is objects[i]
