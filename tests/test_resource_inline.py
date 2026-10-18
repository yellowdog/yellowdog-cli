"""
A resource specified on the command line rather than in a file: 'yd resource
create --type Keyring --set name=k' (and 'remove'), and a specification
read from standard input ('-'). Both reach the loader's one path: variable
substitution, the schema check, '--validate', the source directory stamp.
"""

import io
import json
from types import SimpleNamespace

import pytest

from yellowdog_cli.utils import load_resources
from yellowdog_cli.utils.args import CLIParser
from yellowdog_cli.utils.command_registry import RESOURCE_TYPE_CHOICES


def _parse(command: str, *argv: str) -> CLIParser:
    return CLIParser(command=command, argv=list(argv))


def _refused(command: str, argv: list[str], message: str, capsys) -> None:
    with pytest.raises(SystemExit) as raised:
        _parse(command, *argv)
    assert raised.value.code == 2
    assert message in capsys.readouterr().err


# The command line


def test_the_types_are_those_the_loader_creates():
    assert set(RESOURCE_TYPE_CHOICES) == set(load_resources.RESOURCE_CREATION_ORDER)


@pytest.mark.parametrize("typed", ["Keyring", "keyring", "KEYRING"])
def test_a_type_is_matched_whatever_its_case(typed):
    args = _parse("yd-create", "--type", typed, "--set", "name=k")
    assert args.resource_type == "Keyring"
    assert args.resource_properties == ["name=k"]
    assert args.resource_specifications == []


@pytest.mark.parametrize("command", ["yd-create", "yd-remove"])
def test_an_unknown_type_is_refused(command, capsys):
    _refused(command, ["--type", "Keyrings", "--set", "name=k"], "--type", capsys)


@pytest.mark.parametrize(
    "argv, message",
    [
        ([], "give a resource specification"),
        (["--set", "name=k"], "--set needs --type"),
        (["--type", "Keyring", "--set", "name"], "'name' is not of the form"),
        (["--type", "Keyring", "--set", "=k"], "'=k' is not of the form"),
        (
            ["--type", "Keyring", "--set", "name=a", "--set", "name=b"],
            "--set name is given twice",
        ),
        (
            ["--type", "Keyring", "--set", "resource=Namespace"],
            "give the resource type with --type",
        ),
        (["-", "-"], "'-' (standard input) can be given once"),
    ],
)
def test_what_is_refused_as_parsed(argv, message, capsys):
    _refused("yd-create", argv, message, capsys)


def test_ids_take_no_inline_resource(capsys):
    _refused(
        "yd-remove",
        ["--ids", "--type", "Keyring", "--set", "name=k"],
        "--type and --set specify a resource, not --ids",
        capsys,
    )


def test_files_stdin_and_an_inline_resource_together_are_accepted():
    args = _parse("yd-create", "a.json", "-", "--type", "Namespace", "--set", "name=n")
    assert args.resource_specifications == ["a.json", "-"]


# The loader


@pytest.fixture
def load(monkeypatch, tmp_path):
    """
    Load as yd-create (or, with creation=False, yd-remove) would, from the
    command line's parts given; the schema check recorded rather than run.
    """
    checked: list[str] = []
    monkeypatch.setattr(
        load_resources,
        "warn_of_violations",
        lambda family, document, source: checked.append(source),
    )
    monkeypatch.chdir(tmp_path)

    def _load(
        specifications=(), resource_type=None, properties=(), creation=True, stdin=""
    ):
        monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
        resources = load_resources.load_resource_specifications(
            SimpleNamespace(
                resource_specifications=list(specifications),
                resource_type=resource_type,
                resource_properties=list(properties),
                jsonnet_dry_run=False,
                validate=False,
                no_resequence=False,
            ),
            creation_or_update=creation,
        )
        return resources, checked

    return _load


def test_an_inline_resource_is_built_from_its_properties(load, tmp_path):
    (resource,), checked = load(
        resource_type="StringAttributeDefinition",
        properties=[
            "name=gpu",
            "title=GPU type",
            'options=["a100", "h100"]',
            "description=",
        ],
    )
    assert resource.pop(load_resources.RESOURCE_SOURCE_DIR) == str(tmp_path)
    assert resource == {
        "resource": "StringAttributeDefinition",
        "name": "gpu",
        "title": "GPU type",
        "options": ["a100", "h100"],
        "description": "",
    }
    assert checked == ["the command line"]


def test_a_value_is_read_as_property_overrides_read_it(load):
    (resource,), _ = load(
        resource_type="NamespacePolicy",
        properties=["namespace=123", "autoscalingMaxNodes=10", "x=true", "y=null"],
    )
    # 'namespace' is a string property, so '123' stays text
    assert resource["namespace"] == "123"
    assert resource["autoscalingMaxNodes"] == 10
    assert resource["x"] is True and resource["y"] is None


def test_a_value_has_its_variables_substituted(load, monkeypatch):
    monkeypatch.setattr(
        load_resources,
        "resolve_variables_insitu",
        lambda resource, **k: resource.update(
            name=resource["name"].replace("{{t}}", "dev")
        ),
    )
    (resource,), _ = load(resource_type="Keyring", properties=["name={{t}}-keys"])
    assert resource["name"] == "dev-keys"


def test_an_inline_resource_is_removed_by_the_same_specification(load):
    (resource,), checked = load(
        resource_type="Keyring", properties=["name=k"], creation=False
    )
    assert resource["resource"] == "Keyring" and resource["name"] == "k"
    assert checked == []  # removal reads names alone, as for a file


def test_a_specification_is_read_from_standard_input(load, tmp_path):
    resources, checked = load(
        specifications=["-"],
        stdin=json.dumps(
            [
                {"resource": "Keyring", "name": "a"},
                {"resource": "Namespace", "name": "n"},
            ]
        ),
    )
    assert sorted(r["name"] for r in resources) == ["a", "n"]
    assert all(
        r[load_resources.RESOURCE_SOURCE_DIR] == str(tmp_path) for r in resources
    )
    assert checked == ["standard input"]


def test_standard_input_that_is_not_json_is_named(load):
    with pytest.raises(ValueError, match="Invalid JSON in standard input"):
        load(specifications=["-"], stdin="{not json")


def test_files_standard_input_and_an_inline_resource_are_all_loaded(load, tmp_path):
    (tmp_path / "a.json").write_text(
        '{"resource": "Keyring", "name": "from-file"}', encoding="utf-8"
    )
    resources, _ = load(
        specifications=["a.json", "-"],
        stdin='{"resource": "Keyring", "name": "from-stdin"}',
        resource_type="Keyring",
        properties=["name=inline"],
    )
    assert [r["name"] for r in resources] == ["from-file", "from-stdin", "inline"]


# Removal by name or ID: 'yd resource remove --type <type> <name-or-id>...'

KEYRING_ID = "ydid:keyring:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ALLOWANCE_ID = KEYRING_ID.replace("keyring", "allow")
POOL_ID = KEYRING_ID.replace("keyring", "wrkrpool")


@pytest.mark.parametrize(
    "argv",
    [
        ["--type", "Keyring", "team-keys", KEYRING_ID],
        ["--type", "Allowance", ALLOWANCE_ID],
        ["--type", "Credential", "keyring/credential"],
        ["--type", "ComputeRequirementTemplate", "ns/template", "template"],
        ["--type", "ConfiguredWorkerPool", POOL_ID],
    ],
)
def test_names_and_ids_of_the_type_are_accepted(argv):
    args = _parse("yd-remove", *argv)
    assert args.resource_specifications == argv[2:]


@pytest.mark.parametrize(
    "argv, message",
    [
        (
            ["--type", "Keyring", "k", "--set", "name=j"],
            "give the names or IDs of the resources to remove, or one with --set,"
            " not both",
        ),
        (["--type", "Keyring", POOL_ID], f"'{POOL_ID}' is not the ID of a Keyring"),
        (
            ["--type", "Namespace", KEYRING_ID],
            f"'{KEYRING_ID}' is not the ID of a Namespace",
        ),
        (
            ["--type", "Allowance", "gpu-hours"],
            "an Allowance has no name: give its ID, or --set description=",
        ),
        (["--type", "InternalUser", "someone"], "Users cannot be removed"),
        (["--type", "Credential", "credential"], "'keyring/credential'"),
        (["--type", "Keyring", "-"], "'-' (standard input) is not a name"),
    ],
)
def test_what_is_refused_for_removal_by_name(argv, message, capsys):
    _refused("yd-remove", argv, message, capsys)


@pytest.mark.parametrize(
    "resource_type, target, expected",
    [
        ("Keyring", "k", {"name": "k"}),
        ("Namespace", "dev", {"name": "dev"}),
        ("Group", "g", {"name": "g"}),
        ("Application", "a", {"name": "a"}),
        ("StringAttributeDefinition", "gpu", {"name": "gpu"}),
        ("NamespacePolicy", "dev", {"namespace": "dev"}),
        ("ComputeRequirementTemplate", "t", {"namespace": "ns", "name": "t"}),
        ("ComputeRequirementTemplate", "other/t", {"namespace": "other", "name": "t"}),
        ("MachineImageFamily", "f", {"namespace": "ns", "name": "f"}),
        ("ConfiguredWorkerPool", "p", {"namespace": "ns", "name": "p"}),
        ("ComputeSourceTemplate", "s", {"namespace": "ns", "source": {"name": "s"}}),
        ("Credential", "kr/c", {"keyringName": "kr", "credential": {"name": "c"}}),
    ],
)
def test_a_name_is_the_specification_removal_reads(resource_type, target, expected):
    from yellowdog_cli.utils.resource_targets import specification_for_name

    assert specification_for_name(resource_type, target, "ns") == {
        "resource": resource_type,
        **expected,
    }


def test_names_and_ids_are_removed_in_one_run(monkeypatch):
    from yellowdog_cli.utils import resource_removal
    from yellowdog_cli.utils.context import RunContext
    from yellowdog_cli.utils.exit_codes import ReportedFailure

    removed: list = []

    def by_name(ctx, resource_type, resource):
        if resource["name"] == "broken":
            raise RuntimeError("no")
        removed.append((resource_type, resource))

    monkeypatch.setattr(resource_removal, "_remove_resource", by_name)
    monkeypatch.setattr(
        resource_removal,
        "_remove_and_record_by_id",
        lambda ctx, resource_id: removed.append(resource_id),
    )
    failed: list = []
    monkeypatch.setattr(
        resource_removal,
        "record_resource",
        lambda *args, **kwargs: failed.append(args),
    )
    ctx = RunContext(args=None, config=SimpleNamespace(namespace="ns"), client=None)
    with pytest.raises(ReportedFailure):
        resource_removal.remove_resources_by_name_or_id(
            ctx, "Keyring", ["a", "broken", KEYRING_ID, "a"]
        )
    # Each once, in order; a failure recorded and the rest still attempted
    assert removed == [("Keyring", {"name": "a"}), KEYRING_ID]
    assert failed[0][:2] == ("Keyring", "broken")
    assert failed[0][3] == "failed"


def test_every_type_is_removed_by_name_or_id_or_refused():
    from yellowdog_cli.utils.resource_targets import ID_TYPES, NAMED_TYPES, USER_TYPES
    from yellowdog_cli.utils.ydid_utils import REMOVABLE_YDID_TYPES

    assert NAMED_TYPES | set(ID_TYPES) | USER_TYPES == set(RESOURCE_TYPE_CHOICES)
    assert not (NAMED_TYPES | set(ID_TYPES)) & USER_TYPES
    # Each ID is one '--ids' removes
    assert set(ID_TYPES.values()) <= REMOVABLE_YDID_TYPES


# Shown by name or ID: 'yd resource show --type <type> <name-or-id>...'


@pytest.mark.parametrize(
    "argv, shown",
    [
        (["--type", "Keyring", "team-keys", KEYRING_ID], ["team-keys", KEYRING_ID]),
        (["--type", "computerequirementtemplate", "ns/template"], ["ns/template"]),
        (["--type", "Group", "admins", "--show-members"], ["admins"]),
        (["--type", "ComputeSourceTemplate", "t", "--substitute-ids"], ["t"]),
        (["--type", "InternalUser", "someone"], ["someone"]),
        ([KEYRING_ID], [KEYRING_ID]),
        (["--type", "Namespace", "dev"], ["dev"]),
        (["--type", "NamespacePolicy", "dev"], ["dev"]),
        (["--type", "StringAttributeDefinition", "gpu"], ["gpu"]),
        (["--type", "Credential", "kr/aws"], ["kr/aws"]),
        (["--type", "Allowance", ALLOWANCE_ID], [ALLOWANCE_ID]),
    ],
)
def test_names_and_ids_are_shown(argv, shown):
    assert _parse("yd-show", *argv).yellowdog_ids == shown


@pytest.mark.parametrize(
    "argv, message",
    [
        (["team-keys"], "'team-keys' is not a YellowDog ID; give --type"),
        (
            ["--type", "Namespace", KEYRING_ID],
            "a Namespace has no ID; give its name",
        ),
        (["--type", "Keyring", POOL_ID], f"'{POOL_ID}' is not the ID of a Keyring"),
        (
            ["--type", "Allowance", "gpu-hours"],
            "an Allowance has no name; give its ID",
        ),
        (["--type", "Credential", "aws"], "'keyring/credential'"),
    ],
)
def test_what_is_refused_for_showing_by_name(argv, message, capsys):
    _refused("yd-show", argv, message, capsys)
