"""
yd resource export's engine (utils/resource_export.py): the resources chosen,
their dependencies followed, the specifications ordered and written, and
failures reported, with exporters registered by each test returning canned
results.
"""

import json
from types import SimpleNamespace

import pytest
import requests

from yellowdog_cli.utils import interactive, results
from yellowdog_cli.utils.context import RunContext
from yellowdog_cli.utils.entity_names import (
    ET_COMPUTE_REQUIREMENT_TEMPLATES,
    ET_COMPUTE_SOURCE_TEMPLATES,
    ET_IMAGE_FAMILIES,
    ET_KEYRINGS,
    RN_IMAGE_FAMILY,
    RN_KEYRING,
    RN_REQUIREMENT_TEMPLATE,
    RN_SOURCE_TEMPLATE,
)
from yellowdog_cli.utils.exit_codes import (
    ExitCode,
    NotFoundError,
    ReportedFailure,
    classify,
)
from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.resource_export import (
    ExportOptions,
    ExportRecord,
    export_resources,
    export_specifications,
)
from yellowdog_cli.utils.resource_exporters import (
    EXPORTERS,
    Exported,
    Exporter,
    Found,
    Reference,
    Selection,
)

NAMESPACE = "render"


def _ctx() -> RunContext:
    return RunContext(
        args=SimpleNamespace(),
        config=SimpleNamespace(namespace=NAMESPACE),
        client=None,
    )


def _register(
    monkeypatch: pytest.MonkeyPatch,
    export_type: str,
    resource_type: str,
    names: list[str],
    namespaced: bool = True,
    references: dict[str, tuple[Reference, ...]] | None = None,
    notes: dict[str, tuple[str, ...]] | None = None,
    failing: dict[str, Exception] | None = None,
    find_failure: Exception | None = None,
    selections: list[Selection] | None = None,
) -> None:
    """
    Register an exporter for 'export_type' finding 'names' (each filtered by
    the selection's name glob, an exact name in these tests), exporting each
    as {'resource', 'name'}.
    """

    def find(_ctx: RunContext, selection: Selection) -> list[Found]:
        if selections is not None:
            selections.append(selection)
        if find_failure is not None:
            raise find_failure
        return [
            Found(resource_type, name, key=name)
            for name in names
            if selection.name_glob in (None, "*")
            or name.split("/")[-1] == selection.name_glob
        ]

    def export(_ctx: RunContext, found: Found) -> Exported:
        if failing and found.name in failing:
            raise failing[found.name]
        return Exported(
            specification={"resource": resource_type, "name": found.name},
            references=(references or {}).get(found.name, ()),
            notes=(notes or {}).get(found.name, ()),
        )

    monkeypatch.setitem(
        EXPORTERS,
        export_type,
        Exporter(
            namespaced=namespaced,
            find=find,
            export=export,
            resource_type=resource_type,
        ),
    )


@pytest.fixture(autouse=True)
def _only_registered_exporters(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Each test starts with no exporter, registering its own.
    """
    for key in list(EXPORTERS):
        monkeypatch.delitem(EXPORTERS, key)


def _names(specifications: list[dict]) -> list[tuple[str, str]]:
    return [(s["resource"], s["name"]) for s in specifications]


def _templates_and_keyrings(monkeypatch: pytest.MonkeyPatch) -> None:
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [f"{NAMESPACE}/b", f"{NAMESPACE}/a"],
    )
    _register(monkeypatch, ET_KEYRINGS, RN_KEYRING, ["b", "a"], namespaced=False)


def test_specifications_are_in_creation_order_then_by_name(monkeypatch):
    _templates_and_keyrings(monkeypatch)
    specifications, _ = export_specifications(
        _ctx(), ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES, ET_KEYRINGS))
    )
    assert _names(specifications) == [
        (RN_KEYRING, "a"),
        (RN_KEYRING, "b"),
        (RN_SOURCE_TEMPLATE, f"{NAMESPACE}/a"),
        (RN_SOURCE_TEMPLATE, f"{NAMESPACE}/b"),
    ]


def test_a_namespaced_type_is_found_in_the_namespace_and_others_in_none(monkeypatch):
    template_selections: list[Selection] = []
    keyring_selections: list[Selection] = []
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [],
        selections=template_selections,
    )
    _register(
        monkeypatch,
        ET_KEYRINGS,
        RN_KEYRING,
        [],
        namespaced=False,
        selections=keyring_selections,
    )
    export_specifications(
        _ctx(),
        ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES, ET_KEYRINGS), name_glob="x*"),
    )
    assert template_selections == [Selection(namespace=NAMESPACE, name_glob="x*")]
    assert keyring_selections == [Selection(namespace=None, name_glob="x*")]


def test_two_exports_of_the_same_state_are_identical(tmp_path, monkeypatch):
    _templates_and_keyrings(monkeypatch)
    first, second = tmp_path / "first.json", tmp_path / "second.json"
    for file in (first, second):
        export_resources(
            _ctx(),
            ExportOptions(
                types=(ET_COMPUTE_SOURCE_TEMPLATES, ET_KEYRINGS),
                output_file=str(file),
            ),
        )
    assert first.read_bytes() == second.read_bytes()
    assert len(json.loads(first.read_text(encoding="utf-8"))) == 4


def test_stdout_holds_only_the_array(capsys, monkeypatch):
    _templates_and_keyrings(monkeypatch)
    export_resources(_ctx(), ExportOptions(types=()))
    captured = capsys.readouterr()
    assert json.loads(captured.out) == [
        {"resource": RN_SOURCE_TEMPLATE, "name": f"{NAMESPACE}/a"},
        {"resource": RN_SOURCE_TEMPLATE, "name": f"{NAMESPACE}/b"},
    ]
    # The default types leave out the account-wide ones, and say so
    assert ET_KEYRINGS in captured.err and "--all" in captured.err


def test_no_account_wide_warning_when_types_are_named(capsys, monkeypatch):
    _templates_and_keyrings(monkeypatch)
    export_resources(_ctx(), ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES,)))
    assert "--all" not in capsys.readouterr().err


def test_with_an_output_file_stdout_holds_the_message_alone(
    tmp_path, capsys, monkeypatch
):
    _templates_and_keyrings(monkeypatch)
    file = tmp_path / "out.json"
    export_resources(_ctx(), ExportOptions(types=(ET_KEYRINGS,), output_file=str(file)))
    out = capsys.readouterr().out
    assert f"Exported 2 resources to '{file}'" in " ".join(out.split())
    assert "[" not in out


def test_a_jsonnet_output_file_is_written_in_the_jsonnet_style(tmp_path, monkeypatch):
    _templates_and_keyrings(monkeypatch)
    file = tmp_path / "out.jsonnet"
    export_resources(_ctx(), ExportOptions(types=(ET_KEYRINGS,), output_file=str(file)))
    text = file.read_text(encoding="utf-8")
    assert "resource: 'Keyring'" in text and '"resource"' not in text


def test_a_failing_resource_is_skipped_and_the_rest_written_and_the_code_kept(
    tmp_path, capsys, monkeypatch
):
    _register(
        monkeypatch,
        ET_KEYRINGS,
        RN_KEYRING,
        ["a", "b", "c"],
        namespaced=False,
        failing={"b": NotFoundError("Keyring 'b' not found")},
    )
    file = tmp_path / "out.json"
    with pytest.raises(ReportedFailure) as failure:
        export_resources(
            _ctx(), ExportOptions(types=(ET_KEYRINGS,), output_file=str(file))
        )
    assert classify(failure.value) == ExitCode.NOT_FOUND
    assert _names(json.loads(file.read_text(encoding="utf-8"))) == [
        (RN_KEYRING, "a"),
        (RN_KEYRING, "c"),
    ]
    assert "Keyring 'b' not found" in capsys.readouterr().err


def test_a_failing_find_is_reported_and_the_other_types_written(
    tmp_path, capsys, monkeypatch
):
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [],
        find_failure=RuntimeError("search refused"),
    )
    _register(monkeypatch, ET_KEYRINGS, RN_KEYRING, ["a"], namespaced=False)
    file = tmp_path / "out.json"
    with pytest.raises(ReportedFailure) as failure:
        export_resources(
            _ctx(),
            ExportOptions(
                types=(ET_COMPUTE_SOURCE_TEMPLATES, ET_KEYRINGS), output_file=str(file)
            ),
        )
    assert classify(failure.value) == ExitCode.FAILURE
    assert _names(json.loads(file.read_text(encoding="utf-8"))) == [(RN_KEYRING, "a")]
    assert "search refused" in capsys.readouterr().err


def test_a_connection_failure_writes_nothing(tmp_path, monkeypatch):
    _register(
        monkeypatch,
        ET_KEYRINGS,
        RN_KEYRING,
        ["a", "b", "c"],
        namespaced=False,
        failing={"b": requests.exceptions.ConnectionError("connection lost")},
    )
    file = tmp_path / "out.json"
    file.write_text("old", encoding="utf-8")
    with pytest.raises(requests.exceptions.ConnectionError):
        export_resources(
            _ctx(), ExportOptions(types=(ET_KEYRINGS,), output_file=str(file))
        )
    assert file.read_text(encoding="utf-8") == "old"
    assert [p.name for p in tmp_path.iterdir()] == ["out.json"]


def test_a_connection_failure_prints_nothing_to_stdout(capsys, monkeypatch):
    _register(
        monkeypatch,
        ET_KEYRINGS,
        RN_KEYRING,
        ["a", "b"],
        namespaced=False,
        failing={"b": requests.exceptions.ConnectionError("connection lost")},
    )
    with pytest.raises(requests.exceptions.ConnectionError):
        export_resources(_ctx(), ExportOptions(types=(ET_KEYRINGS,)))
    assert capsys.readouterr().out == ""


def _template_chain(
    monkeypatch: pytest.MonkeyPatch, family_selections: list[Selection] | None = None
) -> None:
    """
    A Compute Requirement Template referring to a Compute Source Template,
    both referring to an Image Family.
    """
    family = Reference(ET_IMAGE_FAMILIES, f"{NAMESPACE}/family")
    _register(
        monkeypatch,
        ET_COMPUTE_REQUIREMENT_TEMPLATES,
        RN_REQUIREMENT_TEMPLATE,
        [f"{NAMESPACE}/crt"],
        references={
            f"{NAMESPACE}/crt": (
                Reference(ET_COMPUTE_SOURCE_TEMPLATES, f"{NAMESPACE}/cst"),
                family,
            )
        },
    )
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [f"{NAMESPACE}/cst", f"{NAMESPACE}/other"],
        references={f"{NAMESPACE}/cst": (family,)},
    )
    _register(
        monkeypatch,
        ET_IMAGE_FAMILIES,
        RN_IMAGE_FAMILY,
        [f"{NAMESPACE}/family", f"{NAMESPACE}/unrelated"],
        selections=family_selections,
    )


def test_dependencies_are_followed_transitively_once(monkeypatch):
    _template_chain(monkeypatch)
    specifications, records = export_specifications(
        _ctx(),
        ExportOptions(
            types=(ET_COMPUTE_REQUIREMENT_TEMPLATES,), with_dependencies=True
        ),
    )
    assert _names(specifications) == [
        (RN_IMAGE_FAMILY, f"{NAMESPACE}/family"),
        (RN_SOURCE_TEMPLATE, f"{NAMESPACE}/cst"),
        (RN_REQUIREMENT_TEMPLATE, f"{NAMESPACE}/crt"),
    ]
    assert (
        ExportRecord(
            RN_SOURCE_TEMPLATE,
            f"{NAMESPACE}/cst",
            "exported",
            f"a dependency of {NAMESPACE}/crt",
        )
        in records
    )
    family_records = [r for r in records if r.resource_type == RN_IMAGE_FAMILY]
    assert len(family_records) == 1
    assert family_records[0].outcome == "exported"
    assert family_records[0].reason is not None
    assert family_records[0].reason.startswith("a dependency of ")
    assert (
        ExportRecord(RN_REQUIREMENT_TEMPLATE, f"{NAMESPACE}/crt", "exported", None)
        in records
    )


def test_a_dependency_already_selected_is_exported_once(monkeypatch):
    _template_chain(monkeypatch)
    specifications, records = export_specifications(
        _ctx(),
        ExportOptions(
            types=(ET_COMPUTE_REQUIREMENT_TEMPLATES, ET_IMAGE_FAMILIES),
            with_dependencies=True,
        ),
    )
    assert _names(specifications).count((RN_IMAGE_FAMILY, f"{NAMESPACE}/family")) == 1
    assert (
        ExportRecord(RN_IMAGE_FAMILY, f"{NAMESPACE}/family", "exported", None)
        in records
    )


def test_a_dependency_that_cannot_be_found_is_a_note(capsys, monkeypatch):
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [f"{NAMESPACE}/cst"],
        references={
            f"{NAMESPACE}/cst": (
                Reference(ET_IMAGE_FAMILIES, "elsewhere/family"),  # no exporter
            )
        },
    )
    specifications, _ = export_specifications(
        _ctx(),
        ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES,), with_dependencies=True),
    )
    assert _names(specifications) == [(RN_SOURCE_TEMPLATE, f"{NAMESPACE}/cst")]
    assert "'elsewhere/family' could not be found to export" in " ".join(
        capsys.readouterr().err.split()
    )


def test_a_dependency_is_looked_up_in_its_own_namespace(monkeypatch):
    family_selections: list[Selection] = []
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [f"{NAMESPACE}/cst"],
        references={
            f"{NAMESPACE}/cst": (Reference(ET_IMAGE_FAMILIES, "shared/family"),)
        },
    )
    _register(
        monkeypatch,
        ET_IMAGE_FAMILIES,
        RN_IMAGE_FAMILY,
        ["shared/family"],
        selections=family_selections,
    )
    specifications, _ = export_specifications(
        _ctx(),
        ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES,), with_dependencies=True),
    )
    assert family_selections == [Selection(namespace="shared", name_glob="family")]
    assert (RN_IMAGE_FAMILY, "shared/family") in _names(specifications)


def test_a_dependency_referred_to_twice_is_looked_up_once(monkeypatch):
    family_selections: list[Selection] = []
    _template_chain(monkeypatch, family_selections)
    export_specifications(
        _ctx(),
        ExportOptions(
            types=(ET_COMPUTE_REQUIREMENT_TEMPLATES,), with_dependencies=True
        ),
    )
    assert family_selections == [Selection(namespace=NAMESPACE, name_glob="family")]


def test_a_dependency_that_cannot_be_looked_up_is_recorded_by_its_type(
    monkeypatch,
):
    """
    Recorded as a resource that could not be read is: its resource type and
    its name, not the type word, which with a null name is a failed search.
    """
    _register(
        monkeypatch,
        ET_COMPUTE_SOURCE_TEMPLATES,
        RN_SOURCE_TEMPLATE,
        [f"{NAMESPACE}/cst"],
        references={
            f"{NAMESPACE}/cst": (Reference(ET_IMAGE_FAMILIES, "shared/family"),)
        },
    )
    _register(
        monkeypatch,
        ET_IMAGE_FAMILIES,
        RN_IMAGE_FAMILY,
        ["shared/family"],
        find_failure=RuntimeError("search refused"),
    )
    specifications, records = export_specifications(
        _ctx(),
        ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES,), with_dependencies=True),
    )
    assert _names(specifications) == [(RN_SOURCE_TEMPLATE, f"{NAMESPACE}/cst")]
    assert (
        ExportRecord(RN_IMAGE_FAMILY, "shared/family", "skipped", "search refused")
        in records
    )


@pytest.mark.parametrize(
    "types, refused",
    [((ET_COMPUTE_SOURCE_TEMPLATES,), True), ((ET_KEYRINGS,), False)],
    ids=["namespaced", "account-wide"],
)
def test_an_empty_configured_namespace_is_refused_for_namespaced_types(
    monkeypatch, capsys, types, refused
):
    _templates_and_keyrings(monkeypatch)
    ctx = RunContext(
        args=SimpleNamespace(), config=SimpleNamespace(namespace=""), client=None
    )
    if not refused:
        export_resources(ctx, ExportOptions(types=types))
        return
    with pytest.raises(SystemExit) as exit_:
        export_resources(ctx, ExportOptions(types=types))
    assert exit_.value.code == ExitCode.CONFIGURATION
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "namespace is empty" in captured.err


def test_without_with_dependencies_references_are_not_followed(monkeypatch):
    _template_chain(monkeypatch)
    specifications, records = export_specifications(
        _ctx(), ExportOptions(types=(ET_COMPUTE_REQUIREMENT_TEMPLATES,))
    )
    assert _names(specifications) == [(RN_REQUIREMENT_TEMPLATE, f"{NAMESPACE}/crt")]
    assert len(records) == 1


def test_json_records_each_resource_with_its_outcome(tmp_path, monkeypatch):
    _register(
        monkeypatch,
        ET_KEYRINGS,
        RN_KEYRING,
        ["a", "b"],
        namespaced=False,
        failing={"b": NotFoundError("Keyring 'b' not found")},
    )
    OUTPUT.json_output = True
    with pytest.raises(ReportedFailure):
        export_resources(
            _ctx(),
            ExportOptions(
                types=(ET_KEYRINGS,),
                output_file=str(tmp_path / "out.json"),
            ),
        )
    assert results._ITEMS == [
        {"resource": RN_KEYRING, "name": "a", "id": None, "action": "exported"},
        {
            "resource": RN_KEYRING,
            "name": "b",
            "id": None,
            "action": "skipped",
            "reason": "Keyring 'b' not found",
        },
    ]


def test_interactive_exports_only_what_is_picked(monkeypatch):
    _templates_and_keyrings(monkeypatch)
    picks: list[int] = [2]
    monkeypatch.setattr(
        interactive,
        "get_selected_list_items",
        lambda *_args, **_kwargs: picks,
    )
    specifications, _ = export_specifications(
        _ctx(), ExportOptions(types=(ET_KEYRINGS,), interactive=True)
    )
    assert _names(specifications) == [(RN_KEYRING, "b")]


def test_interactive_selection_keeps_stdout_the_array(capsys, monkeypatch):
    _templates_and_keyrings(monkeypatch)
    monkeypatch.setattr(
        interactive, "get_selected_list_items", lambda *_args, **_kwargs: [1]
    )
    export_resources(_ctx(), ExportOptions(types=(ET_KEYRINGS,), interactive=True))
    assert _names(json.loads(capsys.readouterr().out)) == [(RN_KEYRING, "a")]


def test_notes_go_to_stderr_as_warnings(capsys, monkeypatch):
    _register(
        monkeypatch,
        ET_KEYRINGS,
        RN_KEYRING,
        ["a"],
        namespaced=False,
        notes={"a": ("Keyring 'a': its grants are not exported",)},
    )
    export_resources(_ctx(), ExportOptions(types=(ET_KEYRINGS,)))
    captured = capsys.readouterr()
    assert "its grants are not exported" in captured.err
    assert "grants" not in captured.out
    json.loads(captured.out)


def test_nothing_found_writes_an_empty_array(capsys, monkeypatch):
    _register(monkeypatch, ET_KEYRINGS, RN_KEYRING, [], namespaced=False)
    export_resources(_ctx(), ExportOptions(types=(ET_KEYRINGS,)))
    captured = capsys.readouterr()
    assert json.loads(captured.out) == []
    assert "No resources to export" in captured.err


def test_a_type_with_no_exporter_is_passed_over(monkeypatch):
    _register(monkeypatch, ET_KEYRINGS, RN_KEYRING, ["a"], namespaced=False)
    specifications, _ = export_specifications(
        _ctx(), ExportOptions(types=(ET_COMPUTE_SOURCE_TEMPLATES, ET_KEYRINGS))
    )
    assert _names(specifications) == [(RN_KEYRING, "a")]
