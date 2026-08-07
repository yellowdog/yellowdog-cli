"""
Helpers for the live resource tests.

Every CLI invocation carries '-c tests/resources/test-config.toml' and
'-v run_id=...': the config supplies the namespace and the dummy values, and the
run id keeps concurrent runs from colliding.

Credentials come from the environment, and only from there:

    export YD_KEY=... YD_SECRET=...      # and YD_URL, for a non-default platform

test-config.toml holds no key, secret or URL and imports none -- it names no
credential property at all, so the CLI takes each from the environment. (An
explicitly selected '-c' file outranks the environment only for the properties it
actually defines, which is why omitting them is what hands the decision to the
environment.) Keeping credentials out of the file entirely means the tracked config
references nothing personal, there is no indirection to resolve when a run
authenticates as the wrong account, and the same two variables work for every other
platform-touching test in the suite.

Output is returned but never logged on success. Three creations print secrets -- a
keyring's password, a configured worker pool's token, an application's API key --
so a failure message names the command to re-run rather than quoting what it
printed. For the same reason, never run a live suite with pytest's '--showlocals':
an unhandled exception would then dump every local variable in every frame on the
traceback, including a captured secret sitting in a variable the test never
printed itself.
"""

import json
import os
import time
from datetime import datetime, timezone

import resource_corpus
from cli_test_helpers import shell

_RUN_ID = f"{int(time.time())}-{os.getpid()}"

# Corpus files whose creation can print a secret. yd()/no helper here suppresses
# output on its own -- callers that invoke yd-create on one of these must not
# assert using result.stdout/stderr in a failure message (see the module
# docstring); this set exists so a caller can check membership before deciding
# whether it is safe to quote a command's output. Not consulted by anything in
# this module yet -- Task 7 only exercises keyrings.jsonnet, whose test hard-codes
# the "withhold output" rule inline. Task 8, which creates all three files, is
# what will actually branch on membership; this is not wired-up behaviour today.
SECRET_EMITTING = {
    "keyrings.jsonnet",
    "configured-worker-pools.jsonnet",
    "applications.jsonnet",
}

# Corpus files with at least one specification that cannot be created standalone:
# requirement-templates.jsonnet's staticMin/dynamicMin and configured-worker-pools.
# jsonnet's poolMin (see each file's own header comment). create_compute_requirement
# _template() and create_configured_worker_pool() (create.py) read 'namespace' out
# of the resource dict with a plain subscript before any model is ever built, which
# is stricter than the SDK model's own optional field -- a known finding from
# Tasks 5/6, not a bug for the live layer to work around. create_resources()
# (create.py) catches each resource's exception, continues to the next resource in
# the same file, and only raises (a single RuntimeError, after the whole file) if
# at least one failed -- so running one of these files live still creates every
# *other* resource in it, and 'yd-create' exits non-zero for the file as a whole
# despite that partial success. Not consulted by anything in this module yet --
# Task 7 never creates either file live. Task 8, which drives every live corpus
# file, is what must expect exactly these two files to behave this way, checking
# how many resources were actually created rather than asserting a zero exit
# code; this is not wired-up behaviour today.
KNOWN_PARTIAL_FAILURES = {
    "requirement-templates.jsonnet",
    "configured-worker-pools.jsonnet",
}

# Which specification(s) in a KNOWN_PARTIAL_FAILURES file are expected to fail,
# named by their own base.name() suffix (the part after 'yd-test-{run_id}-') so
# a test can assert *which* resources are missing rather than merely that the
# file's overall exit code is non-zero -- the "make it explicit rather than
# tolerant of any failure" a partial failure demands. Every other specification
# in each file is expected to succeed.
KNOWN_PARTIAL_FAILURE_NAMES: dict[str, frozenset[str]] = {
    "requirement-templates.jsonnet": frozenset(
        {"static-template-min", "dynamic-template-min"}
    ),
    "configured-worker-pools.jsonnet": frozenset({"configured-pool-min"}),
}

# Entity types yd-list has no YellowDog ID for at all ('--ids-only' warns "not
# supported ... they have no YellowDog IDs" and lists nothing) -- so ydids()'s
# before/after diff can never detect one being created, and yd-show cannot look
# one up by ID either (show.py has no branch for either type). Both are
# matched, read, and diffed by a plain field of their own instead (see
# NO_YDID_KEY_FIELD and list_details() below): Attribute Definitions have no ID
# because create_attribute_definition() (create.py) POSTs a raw payload with no
# object identity of its own; Namespace Policies have no ID because there is at
# most one per namespace, keyed by the namespace name itself, the same
# structural shape as the Namespace it governs.
#
# It is that Namespace -- namespace.jsonnet, the resource, not
# namespace-policy.jsonnet -- which is excluded from the live corpus entirely
# (resource_corpus.OFFLINE_ONLY), because nothing in it is created
# run-uniquely. namespace-policy.jsonnet is NOT excluded: the live layer
# creates it like any other corpus file, and it is matched, read and diffed
# through NO_YDID_KEY_FIELD/list_details() below.
NO_YDID_ENTITY_TYPES = {"attribute-definitions", "namespace-policies"}

# The property that uniquely identifies an entity of a NO_YDID_ENTITY_TYPES
# type, in lieu of a YellowDog ID.
NO_YDID_KEY_FIELD: dict[str, str] = {
    "attribute-definitions": "name",
    "namespace-policies": "namespace",
}

# Properties the live comparison must never hold a specification to, each for
# a reason specific to the live layer rather than to any single corpus file --
# so this lives beside SECRET_EMITTING/KNOWN_PARTIAL_FAILURES rather than
# alongside resource_models.NOT_TESTED, which documents the *offline* write
# gate's exclusions instead. mismatches() pops every one of these from the
# specification side before comparing (see _compare_dict), the same way it
# already skips resource_corpus.META_KEYS:
#   - 'tokenTtl': a field of AddConfiguredWorkerPoolRequest, not of the
#     ConfiguredWorkerPool entity yd-show reads (checked directly against the
#     installed SDK) -- structurally unechoable, not merely unechoed.
#   - 'groups'/'keyrings': popped from the specification before
#     AddApplicationRequest is ever built (see resource_models.build_models()'s
#     Application branch); yd-show's own 'groups' key is a live group
#     membership listing added by show.py's own rendering, not an echo of the
#     specification's list, and is empty when applications.jsonnet runs alone
#     (see its own header comment on the groups.jsonnet/keyrings.jsonnet
#     ordering gap) -- comparing it against what was sent would fail for a
#     reason that has nothing to do with whether the CLI transmitted anything
#     correctly.
#   - 'sourceTemplateId' (ComputeRequirementTemplate.sources
#     entries)/'sourceCreatedFromId' (a SourcesAllowance): each names a
#     Compute Source Template by name in the specification, and
#     create_compute_requirement_template()/create_allowance() (create.py)
#     resolve that name to a YellowDog ID before the request is sent -- live
#     evidence (Task 8) that the corpus's own header comments anticipated
#     ("the raw name round-trips as a plain string" offline, but not live).
LIVE_ONLY_EXCLUSIONS: dict[str, str] = {
    "tokenTtl": "AddConfiguredWorkerPoolRequest's own field, not a field of the "
    "ConfiguredWorkerPool entity yd-show reads",
    "groups": "popped before AddApplicationRequest is built; yd-show's 'groups' "
    "is a live membership listing, not an echo of the specification",
    "keyrings": "popped before AddApplicationRequest is built; belongs to no "
    "model and is never echoed by yd-show at all",
    "sourceTemplateId": "yd-create resolves the Compute Source Template name to "
    "a YellowDog ID before sending the request",
    "sourceCreatedFromId": "yd-create resolves the Compute Source Template name "
    "to a YellowDog ID before sending the request",
}

# The class-scoped counterpart to LIVE_ONLY_EXCLUSIONS above: a property name
# that is NOT safe to skip everywhere (unlike every name in the flat dict
# above, none of which collides with a different, correctly-behaving property
# of the same name elsewhere in the corpus), only within one specific
# polymorphic class's own properties. 'userData' is the reason this exists --
# it is a real, correctly-echoed field on every other compute source class
# (confirmed live by this same run), so excluding it globally the way the flat
# dict above does would also hide a real regression on, say,
# AwsInstancesComputeSource.userData. _compare_dict() only consults this when
# the dict it is comparing carries its own 'type' (i.e. is itself the
# polymorphic leaf, such as a ComputeSourceTemplate's nested 'source'), never
# for an unrelated ancestor dict that merely contains one.
#
# SimulatorComputeSource.userData/subregion: addComputeSourceTemplate accepts
# either being set, but yd-show never echoes them back afterwards (probed
# live, Task 8) -- accepted-then-silently-dropped, not rejected outright. This
# is NOT recorded in resource_models.SERVER_ASSIGNED_COVERAGE: that registry's
# contract is "the platform assigns this" (a genuinely server-assigned
# property comes back -- see 'provider'/'traits'/'id', confirmed by this same
# run), not "this suite cannot confirm it landed". Recording it there would
# also silently drop both out of the write gate's demand forever, with no way
# to notice a future platform fix. Both stay in the corpus
# (source-templates.jsonnet's simulatorMax still sets them, so the write gate still
# demands and exercises them) and are skipped here, live-comparison only, with
# the observation recorded verbatim.
LIVE_ONLY_EXCLUSIONS_BY_CLASS: dict[str, dict[str, str]] = {
    "SimulatorComputeSource": {
        "userData": "addComputeSourceTemplate accepts it, but yd-show never "
        "echoes it back for a SimulatorComputeSource specifically -- accepted, "
        "then silently dropped, unlike every other compute source class where "
        "userData is genuinely settable and correctly echoed",
        "subregion": "addComputeSourceTemplate accepts it, but yd-show never "
        "echoes it back -- the only compute source class that declares this "
        "field at all, so there is no other class's behaviour to compare it "
        "against",
    },
}


def run_id() -> str:
    return _RUN_ID


def command_line(command: str, *args: str) -> str:
    """
    The exact shell command yd() would run, without running it.

    Exists for a caller that needs to *schedule* an invocation rather than run it
    immediately -- e.g. the 'cleanup' fixture, which only accepts a command string
    and runs it later, in its own teardown, regardless of how the test exits.

    Always prefixed with 'cd <CORPUS_DIR> &&', the same convention every other
    system test module already uses for its own 'cleanup(...)' registrations
    (e.g. test_system_lifecycle.py's "cd {SYSTEM_DIR} && yd-shutdown ..."):
    'cleanup' (conftest.py) runs a registered command exactly as given, with no
    chdir of its own, from whatever directory the test process happens to be in
    by teardown time -- which is not reliably CORPUS_DIR, since a test that
    chdir's for the duration of a call (load_corpus_file(), the atexit sweep in
    conftest.py's own run_id fixture) always restores the original directory
    afterwards. Nine of the ten live corpus files start with "local base =
    import 'lib/base.libsonnet'" (all but namespace-policy.jsonnet, which
    needs no shared fragment), which Jsonnet resolves relative to the
    process's cwd, not to the file doing the importing (see
    resource_corpus.load_corpus_file()'s own docstring) -- so a create/remove
    invocation that runs from anywhere else fails outright with "couldn't open
    import ... no match locally or in the Jsonnet library paths", a live-only
    finding (Task 8) invisible to the in-process loader tests, which already
    chdir themselves. CORPUS_DIR is absolute (built from Path(__file__).parent),
    so this is safe to prepend unconditionally, including for a command (like
    yd-list/yd-show) that never touches a corpus file at all.
    """
    parts = [
        "cd",
        str(resource_corpus.CORPUS_DIR),
        "&&",
        command,
        "-c",
        str(resource_corpus.TEST_CONFIG),
        "-v",
        f"run_id={_RUN_ID}",
        *args,
    ]
    return " ".join(parts)


def yd(command: str, *args: str):
    """Run a yd-* command against the test config, with the run id substituted."""
    return shell(command_line(command, *args))


def ydids(entity_type: str, namespace: str | None = None) -> set[str]:
    """The YDIDs of every entity of this type. '-D' is --ids-only, not --dry-run."""
    namespace_arg = "-n=''" if namespace is None else f"-n={namespace}"
    result = yd("yd-list", entity_type, "-D", namespace_arg, "-t=''")
    return {
        line.strip()
        for line in result.stdout.splitlines()
        if line.strip().startswith("ydid:")
    }


def list_details(entity_type: str, namespace: str | None = None) -> list[dict]:
    """
    Every entity of this type, with its full properties -- the NO_YDID_ENTITY_TYPES
    substitute for ydids()+show(): yd-list's own '--details --json' already returns
    each entity's full property set for these two types (checked directly; Attribute
    Definitions and Namespace Policies have no separate 'show' rendering to diverge
    from in the first place), so there is no separate per-entity fetch to make.
    """
    namespace_arg = "-n=''" if namespace is None else f"-n={namespace}"
    result = yd("yd-list", entity_type, "--details", "-J", "-q", namespace_arg, "-t=''")
    # Live evidence (Task 8): '--json' prints nothing at all -- not even '[]' --
    # when nothing matches, unlike a normal, non-empty result.
    return json.loads(result.stdout) if result.stdout.strip() else []


def current_keys(entity_type: str, namespace: str | None = None) -> set[str]:
    """
    The identifying key of every entity of this type that currently exists -- a
    YDID for a normal entity_type, or the NO_YDID_KEY_FIELD value (a name, or a
    namespace) for one of NO_YDID_ENTITY_TYPES -- so a before/after diff works the
    same way regardless of which kind of entity_type is given.
    """
    if entity_type not in NO_YDID_ENTITY_TYPES:
        return ydids(entity_type, namespace)
    key_field = NO_YDID_KEY_FIELD[entity_type]
    return {entity[key_field] for entity in list_details(entity_type, namespace)}


def fetch(entity_type: str, key: str, namespace: str | None = None) -> dict:
    """
    The full properties of one entity, identified by whatever current_keys()
    returned for it -- show() for a normal entity_type (key is its YDID), or a
    NO_YDID_KEY_FIELD lookup through list_details() otherwise.
    """
    if entity_type not in NO_YDID_ENTITY_TYPES:
        return show(key)
    key_field = NO_YDID_KEY_FIELD[entity_type]
    for entity in list_details(entity_type, namespace):
        if entity[key_field] == key:
            return entity
    raise AssertionError(f"{entity_type} entity with {key_field}={key!r} not found")


def load_corpus_file(path) -> list[dict]:
    """
    Load a corpus file in-process the way resource_corpus.load_corpus_file() does,
    but with '{{run_id}}' resolving to this run's own id rather than
    resource_corpus's 'offline' default -- so the names this produces match the
    names a live 'yd-create' subprocess (given the same run id by yd()) actually
    created, which is what lets a caller match a returned entity back to the
    specification that produced it.

    Installs resource_corpus's other dummy values the same way
    resource_corpus.install_variables() does, then overrides that one key. The
    snapshot install_variables() returns already records what 'run_id' held before
    either change, so a single remove_variables() undoes both -- including the case
    where 'run_id' already had some other value, which is restored rather than
    deleted.
    """
    from yellowdog_cli.utils.variables import (
        VARIABLE_SUBSTITUTIONS,
        _update_and_resolve_substitutions,
    )

    previous = resource_corpus.install_variables()
    # Through the same helper install_variables() uses, so the override gets the
    # resolution pass rather than being written straight into the dict.
    _update_and_resolve_substitutions({**VARIABLE_SUBSTITUTIONS, "run_id": _RUN_ID})
    try:
        return resource_corpus.load_corpus_file(path)
    finally:
        resource_corpus.remove_variables(previous)


def show(ydid: str) -> dict:
    result = yd("yd-show", "--quiet", ydid)
    assert result.exit_code == 0, f"yd-show {ydid} failed"
    return json.loads(result.stdout)


def mismatches(spec: dict, returned: dict, path: str = "") -> list[str]:
    """
    Every property the specification set whose returned value differs.

    Properties the platform does not echo are reported, so a silently-dropped
    property is visible rather than assumed fine. Uses resource_models.comparable()
    for the actual leaf-level value comparison -- the same normalisation the
    offline model checks use, rather than a second one -- which is also where the
    fully-qualified 'type' suffix match (a Task 1 finding: 'source.type' comes back
    as 'co.yellowdog.platform.model.AwsInstancesComputeSource' where the
    specification sent the short name) lives, so both directions of comparison
    share one rule, including for a 'type' discriminator nested inside a list
    element (requirement-templates.jsonnet's constraints/preferences, each of
    which carries one) -- not just one sent as a bare top-level property.
    """
    return _compare_dict(spec, returned, path)


def _compare_dict(expected: dict, actual: dict, path: str) -> list[str]:
    """The 'both sides are a dict' case of _compare(), and the top level's too --
    mismatches() is a thin wrapper over this so a nested dict does not need a
    second copy of the same field-by-field, META_KEYS-skipping loop.

    'expected's own 'type' (if it carries one -- only a polymorphic leaf does,
    e.g. an Allowance, a ComputeRequirementTemplate, or a ComputeSourceTemplate's
    nested 'source') identifies which LIVE_ONLY_EXCLUSIONS_BY_CLASS entry, if
    any, applies to *this* dict's own properties -- never to an ancestor's or a
    sibling's, so a class-scoped exclusion can never bleed into an unrelated
    class the way a flat name-based one could.
    """
    class_exclusions = {}
    if "type" in expected:
        import resource_models

        class_exclusions = LIVE_ONLY_EXCLUSIONS_BY_CLASS.get(
            resource_models.comparable(str(expected["type"])), {}
        )
    problems: list[str] = []
    for name, sub_expected in expected.items():
        if (
            name in resource_corpus.META_KEYS
            or name in LIVE_ONLY_EXCLUSIONS
            or name in class_exclusions
        ):
            continue
        where = f"{path}{name}"
        if name not in actual:
            problems.append(f"{where}: not echoed by yd-show")
            continue
        if name in _NATURAL_LANGUAGE_DATE_PROPERTIES:
            problems += _compare_natural_language_date(
                sub_expected, actual[name], where
            )
            continue
        if (
            name in _ORDER_INSENSITIVE_PROPERTIES
            and isinstance(sub_expected, list)
            and isinstance(actual[name], list)
        ):
            problems += _compare_order_insensitive_list(
                sub_expected, actual[name], where
            )
            continue
        problems += _compare(sub_expected, actual[name], where)
    return problems


# Properties whose list order is not semantic, each because live evidence
# (Task 8) showed the platform actually reordering it: an Allowance's
# monitoredStatuses came back ['RUNNING', 'PENDING'] where the specification
# sent ['PENDING', 'RUNNING'], and a Group's roles came back with
# 'work-manager' before 'work-viewer' where the specification sent the other
# way round -- both plain, unordered sets from the specification's own point
# of view. Deliberately narrow, not "every list at every depth": a dynamic
# template's ranked 'preferences' (weight/rankOrder only mean anything in a
# specific order), a static template's 'sources', and a ComputeSourceTemplate's
# 'attributes' are all still compared positionally, so a real reordering bug in
# any of those still fails loudly rather than being silently tolerated the way
# a blanket order-insensitive comparison would. Because of this narrowing,
# "source-templates.jsonnet's attributes round-trips in order" is not a claim this
# suite can make either way -- positional comparison happening to pass one run
# does not distinguish "returned in order" from "returned reordered, but this
# run's permutation of a 2-element list happened to still line up compared
# unluckily" (moot here, since it is not on this list at all -- named only for
# the general point).
_ORDER_INSENSITIVE_PROPERTIES = {"monitoredStatuses", "roles"}


def _compare_order_insensitive_list(
    expected: list, actual: list, where: str
) -> list[str]:
    """
    Accepts 'actual' as a match for 'expected' regardless of order: if some
    permutation of 'actual' makes every element match its counterpart with no
    problems at all, the list is accepted as-is. A length mismatch is reported
    on its own, once (no permutation of a different-length list can ever
    match, so this is checked first rather than tried uselessly); when no
    permutation matches either, the positional, element-by-element diff below
    still runs, so a genuine content difference is reported with a specific
    indexed path rather than a single 'the list differs' message. Permutations
    are only attempted up to 6 elements -- comfortably above every list this
    corpus produces (2-3 elements) -- since the cost is factorial in list
    length.
    """
    import itertools

    if len(expected) == len(actual) and len(expected) <= 6:
        for permutation in itertools.permutations(actual):
            if all(
                not _compare(sub_expected, sub_actual, where)
                for sub_expected, sub_actual in zip(expected, permutation)
            ):
                return []

    problems = []
    if len(expected) != len(actual):
        problems.append(f"{where}: sent {len(expected)} element(s), got {len(actual)}")
    for index, (sub_expected, sub_actual) in enumerate(zip(expected, actual)):
        problems += _compare(sub_expected, sub_actual, f"{where}[{index}]")
    return problems


# An Allowance's effectiveFrom/effectiveUntil, matching the README's own
# examples (allowances.jsonnet's own header comment): create_allowance()
# (create.py) resolves each through dateparser at the moment 'yd-create' sends
# the request, so no fixed expected value can ever be compared for equality --
# see _compare_natural_language_date() for why these two need their own
# comparison rather than the general leaf-level one.
_NATURAL_LANGUAGE_DATE_PROPERTIES = {"effectiveFrom", "effectiveUntil"}


def _compare_natural_language_date(
    expected: object, actual: object, where: str
) -> list[str]:
    """
    effectiveFrom/effectiveUntil are natural-language strings in the corpus
    ('Now', 'After six months'), not ISO datetimes -- create_allowance() feeds
    each through dateparser at the exact moment 'yd-create' sends the request,
    so the instant it resolves to depends on wall-clock time. Live evidence
    (Task 8): re-resolving the same string here, when this comparison runs
    (necessarily some seconds after creation), does not reproduce that exact
    instant even for a spec-side bug-free round trip, so exact string equality
    (what the general leaf-level comparison would do) fails every single
    Allowance on clock drift alone, never on an actual bug.

    A five-minute tolerance -- comfortably above how long a single corpus
    file's create-then-show takes -- is used instead: a real bug (the wrong
    property compared, a garbled date, 'six months' silently becoming 'six
    days') still fails this, while ordinary clock drift between 'sent' and
    'compared' does not.
    """
    import dateparser

    if not isinstance(expected, str) or not isinstance(actual, str):
        return [f"{where}: sent {expected!r}, got {actual!r}"]

    parsed_expected = dateparser.parse(
        expected, settings={"RETURN_AS_TIMEZONE_AWARE": True}
    )
    try:
        parsed_actual = datetime.fromisoformat(actual.replace("Z", "+00:00"))
    except ValueError:
        parsed_actual = None

    if parsed_expected is None or parsed_actual is None:
        return [
            f"{where}: sent {expected!r}, got {actual!r} (could not parse as a date)"
        ]

    if parsed_expected.tzinfo is None:
        parsed_expected = parsed_expected.replace(tzinfo=timezone.utc)

    delta = abs((parsed_expected - parsed_actual).total_seconds())
    if delta > 300:
        return [
            f"{where}: sent {expected!r} (resolved to "
            f"{parsed_expected.isoformat()}), got {actual!r}, {delta:.0f}s apart"
        ]
    return []


def _compare(expected: object, actual: object, where: str) -> list[str]:
    """
    The mismatches, if any, between one expected value and one returned value at
    'where' -- a dict recurses field by field (_compare_dict), a list recurses
    element by element, strictly positionally, with an indexed path (e.g.
    'constraints[1].type'), and anything else is a single leaf-level comparison
    via resource_models.comparable().

    Positional, not order-insensitive: order is semantic for most of the lists
    in this corpus (a dynamic template's ranked 'preferences', a static
    template's 'sources', a ComputeSourceTemplate's 'attributes'), so this is
    the correct default -- see _ORDER_INSENSITIVE_PROPERTIES and
    _compare_order_insensitive_list() above for the two properties live
    evidence showed the platform actually reordering, which _compare_dict()
    routes to that function instead of here before this is ever reached. A
    length mismatch is still reported on its own, once, rather than only
    surfacing as a misleading element-by-element diff past the shorter list's
    end.
    """
    import resource_models

    if isinstance(expected, dict) and isinstance(actual, dict):
        return _compare_dict(expected, actual, f"{where}.")

    if isinstance(expected, list) and isinstance(actual, list):
        problems = []
        if len(expected) != len(actual):
            problems.append(
                f"{where}: sent {len(expected)} element(s), got {len(actual)}"
            )
        for index, (sub_expected, sub_actual) in enumerate(zip(expected, actual)):
            problems += _compare(sub_expected, sub_actual, f"{where}[{index}]")
        return problems

    if resource_models.comparable(expected) != resource_models.comparable(actual):
        return [f"{where}: sent {expected!r}, got {actual!r}"]
    return []
