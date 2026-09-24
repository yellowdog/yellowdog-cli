"""
Unit tests for yellowdog_cli.nodeaction parsing helpers.

Covers:
  - _parse_node_worker_target: PER_NODE, PER_VCPU, CUSTOM, missing fields,
    unknown type
  - _parse_action: all three action types, required fields, optional fields,
    nodeTypes propagation, error paths
  - _parse_action (writeFile): contentFile/contentFiles resolved relative to
    source_dir; absolute paths bypass source_dir; missing files return None;
    __var__ substitution applied to file content
  - _parse_actions: empty list, single, multiple, short-circuit on error
  - _parse_action_groups: empty, single, multiple groups, error propagation,
    missing 'actions' key defaults to empty
  - _load_spec: JSON/Jsonnet dispatch by extension (including uppercase),
    non-dict rejection
  - _submission_error: all four message branches
  - node_action_type_label: all action types, None, unknown
"""

from unittest.mock import patch

import pytest
from yellowdog_client.model import (
    NodeCreateWorkersAction,
    NodeRunCommandAction,
    NodeWorkerTarget,
    NodeWorkerTargetType,
    NodeWriteFileAction,
)

import yellowdog_cli.nodeaction as na_module
from yellowdog_cli.nodeaction import (
    _load_spec,
    _parse_action,
    _parse_action_groups,
    _parse_actions,
    _parse_node_worker_target,
    _submission_error,
)
from yellowdog_cli.utils.printing import node_action_type_label as _action_type_label

# ---------------------------------------------------------------------------
# _parse_node_worker_target
# ---------------------------------------------------------------------------


class TestParseNodeWorkerTarget:
    """
    Parses a nodeWorkers dict into a NodeWorkerTarget.
    Returns None on missing required fields or unknown targetType.
    """

    def test_per_node_returns_correct_target(self):
        result = _parse_node_worker_target({"targetType": "PER_NODE", "targetCount": 2})
        assert isinstance(result, NodeWorkerTarget)
        assert result.targetCount == 2

    def test_per_node_lowercase(self):
        result = _parse_node_worker_target({"targetType": "per_node", "targetCount": 4})
        assert result is not None
        assert result.targetCount == 4

    def test_per_vcpu_returns_correct_target(self):
        result = _parse_node_worker_target(
            {"targetType": "PER_VCPU", "targetCount": 0.5}
        )
        assert isinstance(result, NodeWorkerTarget)
        assert result.targetCount == 0.5

    def test_custom_returns_correct_target(self):
        result = _parse_node_worker_target(
            {"targetType": "CUSTOM", "customTargetCommand": "nproc"}
        )
        assert isinstance(result, NodeWorkerTarget)
        assert result.customTargetCommand == "nproc"

    def test_per_node_missing_count_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_node_worker_target({"targetType": "PER_NODE"})
        assert result is None

    def test_per_vcpu_missing_count_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_node_worker_target({"targetType": "PER_VCPU"})
        assert result is None

    def test_custom_missing_command_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_node_worker_target({"targetType": "CUSTOM"})
        assert result is None

    def test_missing_target_type_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_node_worker_target({"targetCount": 1})
        assert result is None

    def test_unknown_target_type_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_node_worker_target({"targetType": "PER_SOCKET"})
        assert result is None

    def test_per_node_target_type_is_per_node(self):
        result = _parse_node_worker_target({"targetType": "PER_NODE", "targetCount": 1})
        assert result.targetType == NodeWorkerTargetType.PER_NODE

    def test_per_vcpu_target_type_is_per_vcpu(self):
        result = _parse_node_worker_target({"targetType": "PER_VCPU", "targetCount": 2})
        assert result.targetType == NodeWorkerTargetType.PER_VCPU

    def test_custom_target_type_is_custom(self):
        result = _parse_node_worker_target(
            {"targetType": "CUSTOM", "customTargetCommand": "my-cmd"}
        )
        assert result.targetType == NodeWorkerTargetType.CUSTOM

    def test_per_node_count_cast_to_int(self):
        result = _parse_node_worker_target(
            {"targetType": "PER_NODE", "targetCount": 2.9}
        )
        assert result.targetCount == 2

    def test_per_vcpu_count_cast_to_float(self):
        result = _parse_node_worker_target({"targetType": "PER_VCPU", "targetCount": 1})
        assert result.targetCount == 1.0


# ---------------------------------------------------------------------------
# _parse_action
# ---------------------------------------------------------------------------


class TestParseAction:
    """
    Parses a single action dict into the appropriate SDK NodeAction subclass.
    source_dir="." is used for tests that don't exercise path resolution.
    """

    # ------------------------------------------------------------------
    # runCommand
    # ------------------------------------------------------------------

    def test_run_command_minimal(self):
        result = _parse_action({"type": "runCommand", "path": "/bin/echo"}, ".")
        assert isinstance(result, NodeRunCommandAction)
        assert result.path == "/bin/echo"
        assert result.arguments is None
        assert result.environment is None
        assert result.nodeTypes is None

    def test_run_command_full(self):
        spec = {
            "type": "runCommand",
            "path": "/bin/bash",
            "arguments": ["-c", "echo hi"],
            "environment": {"FOO": "bar"},
            "nodeTypes": ["controller"],
        }
        result = _parse_action(spec, ".")
        assert isinstance(result, NodeRunCommandAction)
        assert result.path == "/bin/bash"
        assert result.arguments == ["-c", "echo hi"]
        assert result.environment == {"FOO": "bar"}
        assert result.nodeTypes == ["controller"]

    def test_run_command_missing_path_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action({"type": "runCommand"}, ".")
        assert result is None

    def test_run_command_multiple_node_types(self):
        result = _parse_action(
            {
                "type": "runCommand",
                "path": "/start.sh",
                "nodeTypes": ["slurmctld", "worker"],
            },
            ".",
        )
        assert result.nodeTypes == ["slurmctld", "worker"]

    # ------------------------------------------------------------------
    # writeFile — inline content
    # ------------------------------------------------------------------

    def test_write_file_minimal(self):
        result = _parse_action({"type": "writeFile", "path": "/tmp/out.txt"}, ".")
        assert isinstance(result, NodeWriteFileAction)
        assert result.path == "/tmp/out.txt"
        assert result.content is None
        assert result.nodeTypes is None

    def test_write_file_with_content(self):
        result = _parse_action(
            {"type": "writeFile", "path": "/etc/config", "content": "key=value\n"}, "."
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "key=value\n"

    def test_write_file_missing_path_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action({"type": "writeFile", "content": "data"}, ".")
        assert result is None

    # ------------------------------------------------------------------
    # writeFile — contentFile / contentFiles (absolute paths bypass source_dir)
    # ------------------------------------------------------------------

    def test_write_file_content_file_absolute(self, tmp_path):
        f = tmp_path / "payload.txt"
        f.write_text("hello from file\n")
        result = _parse_action(
            {"type": "writeFile", "path": "/tmp/out.txt", "contentFile": str(f)}, "."
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "hello from file\n"

    def test_write_file_content_files_absolute_concatenated(self, tmp_path):
        a = tmp_path / "a.txt"
        b = tmp_path / "b.txt"
        a.write_text("part-a\n")
        b.write_text("part-b\n")
        result = _parse_action(
            {
                "type": "writeFile",
                "path": "/tmp/out.txt",
                "contentFiles": [str(a), str(b)],
            },
            ".",
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "part-a\npart-b\n"

    def test_write_file_content_file_missing_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "contentFile": "/does/not/exist.txt",
                },
                ".",
            )
        assert result is None

    def test_write_file_content_files_missing_file_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "contentFiles": ["/does/not/exist.txt"],
                },
                ".",
            )
        assert result is None

    def test_write_file_content_files_not_list_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "contentFiles": "/not/a/list.txt",
                },
                ".",
            )
        assert result is None

    def test_write_file_multiple_content_sources_returns_none(self):
        with patch.object(na_module, "print_error") as mock_err:
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "content": "inline",
                    "contentFile": "/some/file.txt",
                },
                ".",
            )
        assert result is None
        mock_err.assert_called_once()

    def test_write_file_content_and_content_files_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "content": "inline",
                    "contentFiles": ["/some/file.txt"],
                },
                ".",
            )
        assert result is None

    def test_write_file_content_file_and_content_files_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "contentFile": "/a.txt",
                    "contentFiles": ["/b.txt"],
                },
                ".",
            )
        assert result is None

    # ------------------------------------------------------------------
    # writeFile — source_dir path resolution
    # ------------------------------------------------------------------

    def test_write_file_content_file_relative_resolved_from_source_dir(self, tmp_path):
        """contentFile given as a bare filename is resolved under source_dir."""
        (tmp_path / "script.sh").write_text("#!/bin/bash\necho hi\n")
        result = _parse_action(
            {
                "type": "writeFile",
                "path": "/tmp/out.sh",
                "contentFile": "script.sh",
            },
            str(tmp_path),
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "#!/bin/bash\necho hi\n"

    def test_write_file_content_files_relative_resolved_from_source_dir(self, tmp_path):
        """Each entry in contentFiles is resolved under source_dir."""
        (tmp_path / "part1.txt").write_text("alpha\n")
        (tmp_path / "part2.txt").write_text("beta\n")
        result = _parse_action(
            {
                "type": "writeFile",
                "path": "/tmp/combined.txt",
                "contentFiles": ["part1.txt", "part2.txt"],
            },
            str(tmp_path),
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "alpha\nbeta\n"

    def test_write_file_content_file_relative_missing_returns_none(self, tmp_path):
        """A relative contentFile not found under source_dir returns None."""
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.txt",
                    "contentFile": "nonexistent.sh",
                },
                str(tmp_path),
            )
        assert result is None

    def test_write_file_content_file_absolute_ignores_source_dir(self, tmp_path):
        """An absolute contentFile path is used as-is regardless of source_dir."""
        other_dir = tmp_path / "other"
        other_dir.mkdir()
        (other_dir / "data.txt").write_text("payload\n")
        # source_dir points elsewhere — absolute path should still resolve
        result = _parse_action(
            {
                "type": "writeFile",
                "path": "/tmp/out.txt",
                "contentFile": str(other_dir / "data.txt"),
            },
            str(tmp_path),
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "payload\n"

    def test_write_file_content_file_subdir_relative(self, tmp_path):
        """Relative paths with a subdirectory component are resolved correctly."""
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "cfg.txt").write_text("cfg-value\n")
        result = _parse_action(
            {
                "type": "writeFile",
                "path": "/etc/cfg",
                "contentFile": "sub/cfg.txt",
            },
            str(tmp_path),
        )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "cfg-value\n"

    # ------------------------------------------------------------------
    # createWorkers
    # ------------------------------------------------------------------

    def test_create_workers_minimal(self):
        result = _parse_action({"type": "createWorkers"}, ".")
        assert isinstance(result, NodeCreateWorkersAction)
        assert result.nodeWorkers is None
        assert result.totalWorkers is None
        assert result.nodeTypes is None

    def test_create_workers_with_per_node_workers(self):
        result = _parse_action(
            {
                "type": "createWorkers",
                "nodeWorkers": {"targetType": "PER_NODE", "targetCount": 2},
            },
            ".",
        )
        assert isinstance(result, NodeCreateWorkersAction)
        assert isinstance(result.nodeWorkers, NodeWorkerTarget)
        assert result.nodeWorkers.targetType == NodeWorkerTargetType.PER_NODE
        assert result.nodeWorkers.targetCount == 2

    def test_create_workers_with_per_vcpu_workers(self):
        result = _parse_action(
            {
                "type": "createWorkers",
                "nodeWorkers": {"targetType": "PER_VCPU", "targetCount": 1},
            },
            ".",
        )
        assert result.nodeWorkers.targetType == NodeWorkerTargetType.PER_VCPU

    def test_create_workers_with_custom_workers(self):
        result = _parse_action(
            {
                "type": "createWorkers",
                "nodeWorkers": {
                    "targetType": "CUSTOM",
                    "customTargetCommand": "calc-workers",
                },
            },
            ".",
        )
        assert result.nodeWorkers.targetType == NodeWorkerTargetType.CUSTOM
        assert result.nodeWorkers.customTargetCommand == "calc-workers"

    def test_create_workers_with_total_workers(self):
        result = _parse_action({"type": "createWorkers", "totalWorkers": 4}, ".")
        assert result.totalWorkers == 4

    def test_create_workers_invalid_node_workers_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action(
                {"type": "createWorkers", "nodeWorkers": {"targetType": "PER_NODE"}},
                ".",
            )
        assert result is None

    def test_create_workers_with_node_types(self):
        result = _parse_action(
            {
                "type": "createWorkers",
                "nodeWorkers": {"targetType": "PER_NODE", "targetCount": 1},
                "nodeTypes": ["slurmd"],
            },
            ".",
        )
        assert result.nodeTypes == ["slurmd"]

    # ------------------------------------------------------------------
    # Error paths
    # ------------------------------------------------------------------

    def test_missing_type_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action({"path": "/bin/bash"}, ".")
        assert result is None

    def test_unknown_type_returns_none(self):
        with patch.object(na_module, "print_error"):
            result = _parse_action({"type": "deleteFile", "path": "/tmp/x"}, ".")
        assert result is None

    def test_missing_type_emits_error(self):
        with patch.object(na_module, "print_error") as mock_err:
            _parse_action({"path": "/bin/bash"}, ".")
        mock_err.assert_called_once()

    def test_unknown_type_emits_error(self):
        with patch.object(na_module, "print_error") as mock_err:
            _parse_action({"type": "badType", "path": "/x"}, ".")
        mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# _parse_actions
# ---------------------------------------------------------------------------


class TestParseActions:
    """
    Parses a list of action dicts. Returns None if any action fails.
    """

    def test_empty_list_returns_empty(self):
        assert _parse_actions([], ".") == []

    def test_single_valid_action(self):
        result = _parse_actions([{"type": "runCommand", "path": "/usr/bin/echo"}], ".")
        assert len(result) == 1
        assert isinstance(result[0], NodeRunCommandAction)

    def test_multiple_valid_actions(self):
        specs = [
            {"type": "runCommand", "path": "/bin/bash"},
            {"type": "writeFile", "path": "/tmp/f.txt"},
            {"type": "createWorkers"},
        ]
        result = _parse_actions(specs, ".")
        assert len(result) == 3
        assert isinstance(result[0], NodeRunCommandAction)
        assert isinstance(result[1], NodeWriteFileAction)
        assert isinstance(result[2], NodeCreateWorkersAction)

    def test_one_invalid_action_returns_none(self):
        specs = [
            {"type": "runCommand", "path": "/bin/bash"},
            {"type": "badType"},
        ]
        with patch.object(na_module, "print_error"):
            result = _parse_actions(specs, ".")
        assert result is None

    def test_first_invalid_short_circuits(self):
        """
        Parsing should stop at the first invalid action. Only one error
        is emitted (not one per remaining action).
        """
        specs = [
            {"type": "badType"},
            {"type": "runCommand", "path": "/valid"},
        ]
        with patch.object(na_module, "print_error") as mock_err:
            _parse_actions(specs, ".")
        # Only the first bad action triggers the error; the second spec is
        # never reached because _parse_action returns None for the first.
        assert mock_err.call_count == 1

    def test_all_invalid_returns_none(self):
        specs = [{"type": "x"}, {"type": "y"}]
        with patch.object(na_module, "print_error"):
            result = _parse_actions(specs, ".")
        assert result is None

    def test_preserves_action_order(self):
        specs = [
            {"type": "writeFile", "path": "/a"},
            {"type": "runCommand", "path": "/b"},
        ]
        result = _parse_actions(specs, ".")
        assert isinstance(result[0], NodeWriteFileAction)
        assert isinstance(result[1], NodeRunCommandAction)

    def test_source_dir_threaded_to_parse_action(self, tmp_path):
        """source_dir is passed through to each _parse_action call."""
        (tmp_path / "data.txt").write_text("content\n")
        specs = [
            {"type": "writeFile", "path": "/tmp/out.txt", "contentFile": "data.txt"}
        ]
        result = _parse_actions(specs, str(tmp_path))
        assert result is not None
        assert result[0].content == "content\n"


# ---------------------------------------------------------------------------
# _parse_action_groups
# ---------------------------------------------------------------------------


class TestParseActionGroups:
    """
    Parses a list of action group dicts into NodeActionGroup objects.
    """

    def test_empty_groups_returns_empty(self):
        result = _parse_action_groups([], ".")
        assert result == []

    def test_single_group_single_action(self):
        from yellowdog_client.model import NodeActionGroup

        result = _parse_action_groups(
            [{"actions": [{"type": "runCommand", "path": "/start.sh"}]}], "."
        )
        assert len(result) == 1
        assert isinstance(result[0], NodeActionGroup)
        assert len(result[0].actions) == 1

    def test_single_group_multiple_actions(self):
        result = _parse_action_groups(
            [
                {
                    "actions": [
                        {"type": "runCommand", "path": "/setup.sh"},
                        {"type": "writeFile", "path": "/etc/config"},
                        {"type": "createWorkers"},
                    ]
                }
            ],
            ".",
        )
        assert len(result[0].actions) == 3

    def test_multiple_groups(self):
        specs = [
            {"actions": [{"type": "runCommand", "path": "/a.sh"}]},
            {"actions": [{"type": "writeFile", "path": "/b.txt"}]},
        ]
        result = _parse_action_groups(specs, ".")
        assert len(result) == 2
        assert isinstance(result[0].actions[0], NodeRunCommandAction)
        assert isinstance(result[1].actions[0], NodeWriteFileAction)

    def test_group_with_invalid_action_returns_none(self):
        specs = [{"actions": [{"type": "badType"}]}]
        with patch.object(na_module, "print_error"):
            result = _parse_action_groups(specs, ".")
        assert result is None

    def test_group_missing_actions_key_yields_empty_group(self):
        """A group dict with no 'actions' key defaults to an empty action list."""
        result = _parse_action_groups([{}], ".")
        assert len(result) == 1
        assert result[0].actions == []

    def test_action_group_error_propagates_none(self):
        """If any group fails, the entire result is None."""
        specs = [
            {"actions": [{"type": "runCommand", "path": "/valid.sh"}]},
            {"actions": [{"type": "notAType"}]},
        ]
        with patch.object(na_module, "print_error"):
            result = _parse_action_groups(specs, ".")
        assert result is None

    def test_source_dir_threaded_to_actions(self, tmp_path):
        """source_dir is passed through all group/action layers."""
        (tmp_path / "init.sh").write_text("#!/bin/sh\n")
        specs = [
            {
                "actions": [
                    {
                        "type": "writeFile",
                        "path": "/tmp/init.sh",
                        "contentFile": "init.sh",
                    }
                ]
            }
        ]
        result = _parse_action_groups(specs, str(tmp_path))
        assert result is not None
        assert result[0].actions[0].content == "#!/bin/sh\n"


# ---------------------------------------------------------------------------
# _action_type_label
# ---------------------------------------------------------------------------


class TestActionTypeLabel:
    """
    Returns a short human-readable label for a node action or None.
    """

    def test_none_returns_dash(self):
        assert _action_type_label(None) == "-"

    def test_run_command_includes_path(self):
        action = NodeRunCommandAction(path="/bin/bash")
        label = _action_type_label(action)
        assert label == "runCommand(/bin/bash)"

    def test_write_file_includes_path(self):
        action = NodeWriteFileAction(path="/etc/hosts")
        label = _action_type_label(action)
        assert label == "writeFile(/etc/hosts)"

    def test_create_workers_label(self):
        action = NodeCreateWorkersAction()
        assert _action_type_label(action) == "createWorkers"

    def test_unknown_action_returns_class_name(self):
        """For an unrecognised action subclass, fall back to the class name."""

        class SomeNewAction(NodeRunCommandAction):
            pass

        action = SomeNewAction(path="/x")
        # The match will fall through to the default case
        label = _action_type_label(action)
        assert label == "SomeNewAction"

    def test_run_command_with_long_path(self):
        action = NodeRunCommandAction(path="/usr/local/bin/configure.sh")
        assert "configure.sh" in _action_type_label(action)

    @pytest.mark.parametrize(
        "path, expected_prefix",
        [
            ("/bin/bash", "runCommand("),
            ("/usr/sbin/service", "runCommand("),
        ],
    )
    def test_run_command_parametrized(self, path, expected_prefix):
        action = NodeRunCommandAction(path=path)
        assert _action_type_label(action).startswith(expected_prefix)


# ---------------------------------------------------------------------------
# _load_spec
# ---------------------------------------------------------------------------


class TestLoadSpec:
    """
    Loads and parses a node action spec file (JSON or Jsonnet).
    Dispatches to the Jsonnet loader for .jsonnet extensions (any case)
    and to the JSON loader otherwise. Returns None if the result is not a dict.
    """

    def test_json_file_returns_dict(self, tmp_path):
        f = tmp_path / "spec.json"
        f.write_text('{"actions": []}')
        result = _load_spec(str(f))
        assert result == {"actions": []}

    def test_json_file_array_returns_none(self, tmp_path):
        f = tmp_path / "spec.json"
        f.write_text('[{"type": "runCommand"}]')
        with patch.object(na_module, "print_error"):
            result = _load_spec(str(f))
        assert result is None

    def test_json_file_array_emits_error(self, tmp_path):
        f = tmp_path / "spec.json"
        f.write_text("[]")
        with patch.object(na_module, "print_error") as mock_err:
            _load_spec(str(f))
        mock_err.assert_called_once()

    def test_uppercase_json_extension_uses_json_loader(self, tmp_path):
        f = tmp_path / "spec.JSON"
        f.write_text('{"actions": []}')
        result = _load_spec(str(f))
        assert result == {"actions": []}

    def test_jsonnet_extension_uses_jsonnet_loader(self, tmp_path):
        f = tmp_path / "spec.jsonnet"
        with patch.object(
            na_module,
            "load_jsonnet_file_with_variable_substitutions",
            return_value={"actions": []},
        ) as mock_loader:
            result = _load_spec(str(f))
        mock_loader.assert_called_once()
        assert result == {"actions": []}

    def test_uppercase_jsonnet_extension_uses_jsonnet_loader(self, tmp_path):
        """Regression: .JSONNET must not fall through to the JSON loader."""
        f = tmp_path / "spec.JSONNET"
        with patch.object(
            na_module,
            "load_jsonnet_file_with_variable_substitutions",
            return_value={"actionGroups": []},
        ) as mock_loader:
            result = _load_spec(str(f))
        mock_loader.assert_called_once()
        assert result == {"actionGroups": []}

    def test_mixed_case_jsonnet_extension_uses_jsonnet_loader(self, tmp_path):
        f = tmp_path / "spec.Jsonnet"
        with patch.object(
            na_module,
            "load_jsonnet_file_with_variable_substitutions",
            return_value={"actions": []},
        ) as mock_loader:
            _load_spec(str(f))
        mock_loader.assert_called_once()

    def test_json_loader_not_called_for_jsonnet(self, tmp_path):
        f = tmp_path / "spec.jsonnet"
        with patch.object(
            na_module,
            "load_jsonnet_file_with_variable_substitutions",
            return_value={"actions": []},
        ):
            with patch.object(
                na_module, "load_json_file_with_variable_substitutions"
            ) as mock_json:
                _load_spec(str(f))
        mock_json.assert_not_called()


# ---------------------------------------------------------------------------
# _submission_error
# ---------------------------------------------------------------------------


class TestSubmissionError:
    """
    Returns a human-friendly error message for node action submission failures.
    """

    def test_generic_error_returns_failed_to_submit(self):
        msg = _submission_error(Exception("something went wrong"))
        assert msg == "Failed to submit: something went wrong"

    def test_no_available_nodes_with_node_id(self):
        msg = _submission_error(
            Exception("No available nodes in pool"), node_id="ydid:node:ABC:123"
        )
        assert "ydid:node:ABC:123" in msg
        assert "is it running?" in msg

    def test_no_available_nodes_with_specific_nodes(self):
        msg = _submission_error(Exception("No available nodes"), specific_nodes=True)
        assert "None of the selected nodes" in msg
        assert "are they running?" in msg

    def test_no_available_nodes_no_context_mentions_node_types(self):
        msg = _submission_error(Exception("No available nodes"))
        assert "nodeTypes" in msg

    def test_node_id_takes_priority_over_specific_nodes(self):
        """node_id is checked before specific_nodes."""
        msg = _submission_error(
            Exception("No available nodes"),
            node_id="ydid:node:ABC:123",
            specific_nodes=True,
        )
        assert "ydid:node:ABC:123" in msg

    def test_unrelated_error_does_not_mention_nodes(self):
        msg = _submission_error(Exception("connection timeout"))
        assert "Failed to submit" in msg
        assert "node" not in msg.lower() or "submit" in msg


# ---------------------------------------------------------------------------
# writeFile variable substitution
# ---------------------------------------------------------------------------


class TestWriteFileVariableSubstitution:
    """
    contentFile and contentFiles content has __{{var}}__ substitutions applied
    (WP_VARIABLES_PREFIX/POSTFIX = "__") before being set as the action content.
    """

    def test_content_file_substitution_function_called(self, tmp_path):
        """process_variable_substitutions_in_file_contents is called with the
        raw file content; its return value becomes the action content."""
        f = tmp_path / "script.sh"
        f.write_text("raw content\n")
        with patch.object(
            na_module,
            "process_variable_substitutions_in_file_contents",
            return_value="substituted content\n",
        ) as mock_sub:
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.sh",
                    "contentFile": "script.sh",
                },
                str(tmp_path),
            )
        mock_sub.assert_called_once_with(
            "raw content\n",
            prefix="__",
            postfix="__",
            source="script.sh",
        )
        assert result.content == "substituted content\n"

    def test_content_files_substitution_called_per_part(self, tmp_path):
        """Substitution is applied to each file individually before joining."""
        (tmp_path / "a.sh").write_text("part-a\n")
        (tmp_path / "b.sh").write_text("part-b\n")
        with patch.object(
            na_module,
            "process_variable_substitutions_in_file_contents",
            side_effect=["sub-a\n", "sub-b\n"],
        ) as mock_sub:
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/combined.sh",
                    "contentFiles": ["a.sh", "b.sh"],
                },
                str(tmp_path),
            )
        assert mock_sub.call_count == 2
        assert result.content == "sub-a\nsub-b\n"

    def test_content_file_env_var_substitution(self, tmp_path):
        """__{{env:VAR}}__ is resolved via os.getenv() at substitution time."""
        f = tmp_path / "script.sh"
        f.write_text("echo __{{env:NODEACTION_TEST_VAR}}__\n")
        with patch.dict("os.environ", {"NODEACTION_TEST_VAR": "hello"}):
            result = _parse_action(
                {
                    "type": "writeFile",
                    "path": "/tmp/out.sh",
                    "contentFile": "script.sh",
                },
                str(tmp_path),
            )
        assert isinstance(result, NodeWriteFileAction)
        assert result.content == "echo hello\n"
