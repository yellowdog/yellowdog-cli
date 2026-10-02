"""
yd-provision and yd-instantiate: '--target' overrides the specification
file as well as the configuration, yd-provision's node counts are made
consistent in the specification as it will be sent (not in the TOML values
before they are merged), a missing 'templateId' is a failure, and a failed
Platform call keeps the exit code its kind of failure has.

Each test drives the command's real main() through main_wrapper, with the
client (or the raw HTTP call) mocked.
"""

from json import dumps as json_dumps
from json import loads as json_loads
from unittest.mock import MagicMock

import pytest
import requests
from requests import HTTPError, Response

import yellowdog_cli.instantiate as yd_instantiate
import yellowdog_cli.provision as yd_provision
import yellowdog_cli.utils.interactive as interactive_module
import yellowdog_cli.utils.printing as printing_module
import yellowdog_cli.utils.results as results_module
import yellowdog_cli.utils.wrapper as wrapper_module
from yellowdog_cli.utils.config_types import ConfigWorkerPool
from yellowdog_cli.utils.results import reset_results
from yellowdog_cli.utils.settings import ExitCode

CRT_ID = "ydid:crt:000000:00000000-0000-0000-0000-000000000000"

_DEFAULTS = {
    "json_output": False,
    "dry_run": False,
    "quiet": False,
    "count_only": False,
    "follow": False,
    "auto_cr": False,
    "yes": True,
    "no_format": True,
    "print_pid": False,
    "debug": False,
    "validate": False,
    "jsonnet_dry_run": False,
    "progress": False,
    "target": None,
    "content_path": None,
    "worker_pool_file": None,
    "worker_pool_file_positional": None,
    "compute_requirement": None,
    "compute_requirement_file_positional": None,
    "report": False,
}


def _response(status: int, text: str = "platform says no") -> Response:
    response = Response()
    response.status_code = status
    response._content = text.encode()
    return response


@pytest.fixture()
def run(monkeypatch, capsys):
    """
    Return run(module, config_wp, client=None, user_data=None,
    template_id=None, **args): run module.main() through the wrapper and
    return (stdout, client), the exit code left in run.exit_code and stderr
    in run.err. 'user_data' and 'template_id' stand in for
    get_user_data_property(), which otherwise returns None, and
    get_template_id(), which otherwise returns CRT_ID.
    """
    reset_results()

    def _run(
        module,
        config_wp: ConfigWorkerPool,
        client=None,
        user_data=None,
        template_id=None,
        **values,
    ):
        args = MagicMock(**{**_DEFAULTS, **values})
        client = client or MagicMock()
        for target in (
            module,
            results_module,
            printing_module,
            interactive_module,
            wrapper_module,
        ):
            monkeypatch.setattr(target, "ARGS_PARSER", args)
        monkeypatch.setattr(module, "CLIENT", client)
        monkeypatch.setattr(wrapper_module, "CLIENT", MagicMock())
        monkeypatch.setattr(
            module,
            "CONFIG_COMMON",
            MagicMock(namespace="ns", name_tag="tag", url="https://u"),
        )
        monkeypatch.setattr(module, "CONFIG_WP", config_wp)
        monkeypatch.setattr(
            module, "warn_of_undefined_worker_pool_variables", lambda: None
        )
        monkeypatch.setattr(
            module, "get_template_id", template_id or (lambda *a, **k: CRT_ID)
        )
        monkeypatch.setattr(
            module, "get_user_data_property", user_data or (lambda *a: None)
        )
        monkeypatch.setattr(module, "link_entity", lambda *a: "[link]")
        with pytest.raises(SystemExit) as exit_info:
            module.main()
        _run.exit_code = exit_info.value.code  # type: ignore[attr-defined]
        out, _run.err = capsys.readouterr()  # type: ignore[attr-defined]
        return out, client

    yield _run
    reset_results()


@pytest.fixture()
def wp_file(tmp_path):
    def _write(usage: dict, properties: dict) -> str:
        path = tmp_path / "wp.json"
        path.write_text(
            json_dumps(
                {
                    "requirementTemplateUsage": {"templateId": CRT_ID, **usage},
                    "provisionedProperties": properties,
                }
            )
        )
        return str(path)

    return _write


@pytest.fixture()
def cr_file(tmp_path):
    def _write(usage: dict) -> str:
        path = tmp_path / "cr.json"
        path.write_text(json_dumps({"templateId": CRT_ID, **usage}))
        return str(path)

    return _write


def _provision_dry_run(run, path: str, config_wp=None, **values) -> dict:
    out, _ = run(
        yd_provision,
        config_wp or ConfigWorkerPool(),
        dry_run=True,
        json_output=True,
        worker_pool_file_positional=path,
        **values,
    )
    return json_loads(out)


# ---------------------------------------------------------------------------
# yd-provision: '--target' and the node counts, with a specification file
# ---------------------------------------------------------------------------


class TestProvisionSpecificationNodeCounts:
    def test_target_overrides_the_specification(self, run, wp_file):
        path = wp_file({"targetInstanceCount": 2}, {"maxNodes": 3})
        document = _provision_dry_run(run, path, target=10)
        assert document["requirementTemplateUsage"]["targetInstanceCount"] == 10
        # Raised to match, as the TOML path raises it
        assert document["provisionedProperties"]["maxNodes"] == 10

    def test_target_is_inserted_where_the_specification_has_none(self, run, wp_file):
        path = wp_file({}, {"maxNodes": 3})
        document = _provision_dry_run(run, path, target=2)
        assert document["requirementTemplateUsage"]["targetInstanceCount"] == 2
        assert document["provisionedProperties"]["maxNodes"] == 3

    def test_without_target_the_specification_is_kept(self, run, wp_file):
        path = wp_file({"targetInstanceCount": 2}, {"maxNodes": 3})
        document = _provision_dry_run(run, path)
        assert document["requirementTemplateUsage"]["targetInstanceCount"] == 2
        assert document["provisionedProperties"]["maxNodes"] == 3

    def test_toml_values_are_rationalised_with_the_specifications(self, run, wp_file):
        # 'minNodes' from the TOML file, the target from the specification:
        # each is only consistent with the other once merged
        path = wp_file({"targetInstanceCount": 2}, {"maxNodes": 3})
        document = _provision_dry_run(
            run, path, ConfigWorkerPool(min_nodes=4, min_nodes_set=True)
        )
        assert document["provisionedProperties"]["minNodes"] == 4
        assert document["requirementTemplateUsage"]["targetInstanceCount"] == 4
        assert document["provisionedProperties"]["maxNodes"] == 4

    def test_unset_toml_counts_are_not_reported_as_adjusted(self, run, wp_file):
        # ConfigWorkerPool()'s maxNodes of 0 used to be 'increased' to 1, in a
        # message, though the value was never sent
        path = wp_file({"targetInstanceCount": 2}, {"maxNodes": 3})
        out, _ = run(
            yd_provision,
            ConfigWorkerPool(),
            dry_run=True,
            worker_pool_file_positional=path,
        )
        assert "Increasing" not in out

    def test_counts_absent_from_the_specification_are_left_absent(self, run, wp_file):
        path = wp_file({"targetInstanceCount": 2}, {})
        document = _provision_dry_run(run, path)
        assert "maxNodes" not in document["provisionedProperties"]
        assert "minNodes" not in document["provisionedProperties"]


class TestRationalisedNodeCounts:
    @staticmethod
    def rationalised(*counts):
        return yd_provision._rationalised_node_counts(*counts)

    def test_consistent_counts_are_unchanged(self):
        assert self.rationalised(1, 2, 3) == (1, 2, 3)

    def test_negative_minimum_is_raised_to_zero(self):
        assert self.rationalised(-1, 2, 3) == (0, 2, 3)

    def test_target_is_raised_to_the_minimum(self):
        assert self.rationalised(4, 2, 5) == (4, 4, 5)

    def test_maximum_is_raised_to_the_target(self):
        assert self.rationalised(0, 10, 3) == (0, 10, 10)

    def test_zero_maximum_is_raised_to_one(self):
        assert self.rationalised(0, 0, 0) == (0, 0, 1)
        assert self.rationalised(None, None, 0) == (None, None, 1)

    def test_unknown_counts_are_neither_adjusted_nor_compared(self):
        assert self.rationalised(None, 10, None) == (None, 10, None)
        assert self.rationalised(4, None, 2) == (4, None, 2)


# ---------------------------------------------------------------------------
# yd-provision: failures
# ---------------------------------------------------------------------------


class TestProvisionFailures:
    def test_missing_template_id_is_a_failure(self, run):
        run(yd_provision, ConfigWorkerPool())
        assert run.exit_code == ExitCode.FAILURE

    @pytest.mark.parametrize(
        ("error", "code"),
        [
            (HTTPError("nope", response=_response(404)), ExitCode.NOT_FOUND),
            (HTTPError("nope", response=_response(503)), ExitCode.PLATFORM),
            (requests.ConnectionError("refused"), ExitCode.CONNECTION),
        ],
    )
    def test_toml_path_keeps_the_exit_code(self, run, error, code):
        client = MagicMock()
        client.worker_pool_client.provision_worker_pool.side_effect = error
        run(
            yd_provision,
            ConfigWorkerPool(template_id=CRT_ID, target_instance_count=1),
            client=client,
        )
        assert run.exit_code == code

    @pytest.mark.parametrize(
        ("status", "code"),
        [
            (401, ExitCode.AUTHENTICATION),
            (404, ExitCode.NOT_FOUND),
            (500, ExitCode.PLATFORM),
        ],
    )
    def test_json_path_keeps_the_exit_code(
        self, run, wp_file, monkeypatch, status, code
    ):
        monkeypatch.setattr(
            yd_provision.requests, "post", lambda **k: _response(status)
        )
        run(
            yd_provision,
            ConfigWorkerPool(),
            worker_pool_file_positional=wp_file({"targetInstanceCount": 1}, {}),
        )
        assert run.exit_code == code


# ---------------------------------------------------------------------------
# yd-instantiate
# ---------------------------------------------------------------------------


class TestInstantiate:
    def test_target_overrides_the_specification(self, run, cr_file):
        out, _ = run(
            yd_instantiate,
            ConfigWorkerPool(),
            dry_run=True,
            json_output=True,
            target=7,
            compute_requirement_file_positional=cr_file({"targetInstanceCount": 2}),
        )
        assert json_loads(out)["targetInstanceCount"] == 7

    def test_without_target_the_specification_is_kept(self, run, cr_file):
        out, _ = run(
            yd_instantiate,
            ConfigWorkerPool(target_instance_count=5),
            dry_run=True,
            json_output=True,
            compute_requirement_file_positional=cr_file({"targetInstanceCount": 2}),
        )
        assert json_loads(out)["targetInstanceCount"] == 2

    @pytest.mark.parametrize(
        ("error", "code"),
        [
            (HTTPError("nope", response=_response(404)), ExitCode.NOT_FOUND),
            (requests.ConnectionError("refused"), ExitCode.CONNECTION),
        ],
    )
    def test_toml_path_keeps_the_exit_code(self, run, error, code):
        client = MagicMock()
        client.compute_client.provision_compute_requirement_template.side_effect = error
        run(
            yd_instantiate,
            ConfigWorkerPool(template_id=CRT_ID, target_instance_count=1),
            client=client,
        )
        assert run.exit_code == code

    def test_json_path_keeps_the_exit_code(self, run, cr_file, monkeypatch):
        monkeypatch.setattr(yd_instantiate.requests, "post", lambda **k: _response(503))
        run(
            yd_instantiate,
            ConfigWorkerPool(),
            compute_requirement_file_positional=cr_file({"targetInstanceCount": 1}),
        )
        assert run.exit_code == ExitCode.PLATFORM


# ---------------------------------------------------------------------------
# yd-provision: the template lookup, with a specification file
# ---------------------------------------------------------------------------


class TestProvisionTemplateLookup:
    def test_a_template_not_found_is_not_a_key_error_in_the_file(self, run, wp_file):
        def _not_found(*a, **k):
            raise KeyError("Compute Requirement Template 'nope' not found")

        run(
            yd_provision,
            ConfigWorkerPool(),
            template_id=_not_found,
            worker_pool_file_positional=wp_file({"targetInstanceCount": 1}, {}),
        )
        assert run.exit_code == ExitCode.FAILURE
        assert "Compute Requirement Template 'nope' not found" in run.err
        assert "Key error in JSON Worker Pool definition" not in run.err

    def test_no_template_id_anywhere_is_reported_as_such(self, run, tmp_path):
        path = tmp_path / "wp.json"
        path.write_text(
            json_dumps(
                {
                    "requirementTemplateUsage": {"targetInstanceCount": 1},
                    "provisionedProperties": {},
                }
            )
        )
        run(yd_provision, ConfigWorkerPool(), worker_pool_file_positional=str(path))
        assert run.exit_code == ExitCode.FAILURE
        assert "No 'templateId' supplied" in run.err


# ---------------------------------------------------------------------------
# Reading the TOML user data: once, and only when it is used
# ---------------------------------------------------------------------------


class _UserData:
    """A get_user_data_property() stand-in that counts its calls."""

    def __init__(self, value: str | None = "#!/bin/sh"):
        self.value = value
        self.calls = 0

    def __call__(self, *args):
        self.calls += 1
        return self.value


class TestUserData:
    def test_provision_reads_it_once_for_every_batch(self, run):
        user_data = _UserData()
        client = MagicMock()
        client.worker_pool_client.provision_worker_pool.return_value = MagicMock(
            id="ydid:wrkrpool:000000:1", name="wp"
        )
        run(
            yd_provision,
            ConfigWorkerPool(
                template_id=CRT_ID,
                target_instance_count=3,
                max_nodes=3,
                compute_requirement_batch_size=1,
            ),
            client=client,
            user_data=user_data,
        )
        assert run.exit_code == ExitCode.SUCCESS
        assert client.worker_pool_client.provision_worker_pool.call_count == 3
        assert user_data.calls == 1
        for call in client.worker_pool_client.provision_worker_pool.call_args_list:
            assert call.args[0].userData == "#!/bin/sh"

    def test_instantiate_reads_it_once_for_every_batch(self, run):
        user_data = _UserData()
        client = MagicMock()
        client.compute_client.provision_compute_requirement_template.return_value = (
            MagicMock(id="ydid:compreq:000000:1", name="cr")
        )
        run(
            yd_instantiate,
            ConfigWorkerPool(
                template_id=CRT_ID,
                target_instance_count=3,
                compute_requirement_batch_size=1,
            ),
            client=client,
            user_data=user_data,
        )
        assert run.exit_code == ExitCode.SUCCESS
        provision = client.compute_client.provision_compute_requirement_template
        assert provision.call_count == 3
        assert user_data.calls == 1
        for call in provision.call_args_list:
            assert call.args[0].userData == "#!/bin/sh"

    def test_provision_skips_it_when_the_specification_has_user_data(
        self, run, wp_file
    ):
        user_data = _UserData()
        path = wp_file({"targetInstanceCount": 1, "userData": "spec"}, {})
        document = _provision_dry_run(run, path, user_data=user_data)
        assert user_data.calls == 0
        assert document["requirementTemplateUsage"]["userData"] == "spec"

    def test_provision_inserts_it_when_the_specification_has_none(self, run, wp_file):
        user_data = _UserData()
        path = wp_file({"targetInstanceCount": 1}, {})
        document = _provision_dry_run(run, path, user_data=user_data)
        assert user_data.calls == 1
        assert document["requirementTemplateUsage"]["userData"] == "#!/bin/sh"

    def test_instantiate_skips_it_when_the_specification_has_user_data(
        self, run, cr_file
    ):
        user_data = _UserData()
        out, _ = run(
            yd_instantiate,
            ConfigWorkerPool(),
            user_data=user_data,
            dry_run=True,
            json_output=True,
            compute_requirement_file_positional=cr_file({"userData": "spec"}),
        )
        assert user_data.calls == 0
        assert json_loads(out)["userData"] == "spec"

    def test_instantiate_inserts_it_when_the_specification_has_none(self, run, cr_file):
        user_data = _UserData()
        out, _ = run(
            yd_instantiate,
            ConfigWorkerPool(),
            user_data=user_data,
            dry_run=True,
            json_output=True,
            compute_requirement_file_positional=cr_file({}),
        )
        assert user_data.calls == 1
        assert json_loads(out)["userData"] == "#!/bin/sh"


# ---------------------------------------------------------------------------
# yd-provision: how the TOML path and the merged values are reported
# ---------------------------------------------------------------------------


class TestProvisionMessages:
    def test_timeouts_are_whole_minutes_and_disabled_is_plain(self, run):
        out, _ = run(
            yd_provision,
            ConfigWorkerPool(
                template_id=CRT_ID,
                target_instance_count=1,
                max_nodes=1,
                idle_node_timeout=0,
                idle_pool_timeout=2.5,
            ),
            dry_run=True,
        )
        assert "Node boot time limit is 10 minute(s)" in out
        assert "Node idle shutdown is disabled" in out
        assert "**" not in out
        assert "with a delay of 2.5 minute(s)" in out

    def test_merged_values_are_shown_as_json(self, run, wp_file):
        out, _ = run(
            yd_provision,
            ConfigWorkerPool(),
            dry_run=True,
            worker_pool_file_positional=wp_file({"targetInstanceCount": 1}, {}),
        )
        assert (
            "Setting 'provisionedProperties.idleNodeShutdown':"
            ' \'{"enabled": true, "timeout": "PT5M"}\''
        ) in out
        assert "Setting 'provisionedProperties.metricsEnabled': 'false'" in out
        assert "True" not in out and "False" not in out


class TestMinutes:
    @pytest.mark.parametrize(
        "minutes, shown",
        [(10.0, "10"), (0.5, "0.5"), (2.25, "2.25"), (1440.0, "1,440")],
    )
    def test_whole_minutes_lose_their_fraction(self, minutes, shown):
        assert yd_provision._minutes(minutes) == shown
