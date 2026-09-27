"""
The command's result under '--json': whatever a command records here is
printed once, as one JSON document, by the wrapper when the command returns
or fails. Without '--json' nothing is printed and recording is free.

A command calls record() where it reports an outcome today, alongside the
print_info() that '--json' already silences; a command whose result is one
object calls record_document() instead. Both wrappers call flush_results()
after the command returns and, on a failure, before exiting, so a script sees
what was done before the failure.

This module must not import wrapper.py or load_config.py: the wrappers
import it.
"""

import re
from typing import Any

from yellowdog_client.common.json import Json

from yellowdog_cli.utils.args import ARGS_PARSER
from yellowdog_cli.utils.printing import (
    json_document_printed,
    print_error,
    print_json,
    print_objects_as_json,
    reset_json_document_printed,
)
from yellowdog_cli.utils.ydid_utils import get_ydid_type

_ITEMS: list[Any] = []
_DOCUMENT: Any = None  # Set by record_document(); wins over _ITEMS
_HAS_DOCUMENT = False
_FLUSHED = False
_STREAMED = False  # Set by results_are_streamed()


def record(item: dict | Any) -> None:
    """
    Append one item to the result array: a dict, or an SDK object, which is
    serialised as yd-list serialises it.
    """
    _ITEMS.append(item)


def record_action(
    entity: Any,
    entity_type: str,
    action: str,
    outcome: str,
    error: str | None = None,
    **extra: Any,
) -> None:
    """
    Record one action command's outcome for one entity, as
    {"id", "name", "type", "action", "outcome"} (plus "error" when given,
    and any extra fields, such as yd-resize's "targetInstanceCount").

    'entity' is an SDK object (its 'id' and 'name' are used), a dict with
    'id' and 'name' keys, or a string the command was given: a YellowDog ID
    becomes the 'id' and anything else the 'name', the other being null.
    'entity_type' is the type as yd-list spells it ('work-requirements');
    'action' the verb ('cancel'); 'outcome' the past tense ('cancelled'),
    'skipped', 'failed', or 'would <action>' under '--dry-run'.
    """
    if isinstance(entity, str):
        if get_ydid_type(entity) is not None:
            entity_id, name = entity, None
        else:
            entity_id, name = None, entity
    elif isinstance(entity, dict):
        entity_id, name = entity.get("id"), entity.get("name")
    else:
        entity_id = getattr(entity, "id", None)
        name = getattr(entity, "name", None)

    item: dict[str, Any] = {
        "id": entity_id,
        "name": name,
        "type": entity_type,
        "action": action,
        "outcome": outcome,
    }
    if error is not None:
        item["error"] = error
    item.update(extra)
    record(item)


def record_resource(
    resource_type: str | None,
    name: str | None,
    id: str | None,
    action: str,
    error: str | None = None,
    **extra: Any,
) -> None:
    """
    Record one yd-create or yd-remove outcome for one resource, as
    {"resource", "name", "id", "action"} (plus "error" when given, and any
    extra fields, such as a Keyring's "password").

    'resource_type' is the specification's 'resource' ('Keyring'); 'name'
    the name the command reports it by; 'id' its YellowDog ID, or None when
    unknown; 'action' one of 'created', 'updated', 'removed', 'skipped' or
    'failed'.
    """
    item: dict[str, Any] = {
        "resource": resource_type,
        "name": name,
        "id": id,
        "action": action,
    }
    if error is not None:
        item["error"] = error
    item.update(extra)
    record(item)


def record_entity(
    entity_id: str | None, name: str | None, namespace: str | None, entity_type: str
) -> None:
    """
    Record the entity a yd-submit, yd-provision or yd-instantiate run
    created, as {"id", "name", "namespace", "type"}, 'entity_type' spelled
    as yd-list spells it ('work-requirements'). See record_document_part().
    """
    record_document_part(
        {"id": entity_id, "name": name, "namespace": namespace, "type": entity_type}
    )


_DOCUMENT_PARTS: list[Any] = []


def record_document_part(part: dict | Any) -> None:
    """
    Add one part to a document that is that part alone when there is one,
    and the array of them when there are more: the one entity a creator
    made, unless batching made several, or its one processed specification
    under '--dry-run', likewise. Recorded as each part arrives, so a failure
    part-way still emits the parts made before it.
    """
    _DOCUMENT_PARTS.append(part)
    record_document(
        _DOCUMENT_PARTS[0] if len(_DOCUMENT_PARTS) == 1 else list(_DOCUMENT_PARTS)
    )


def record_document(document: dict | list | Any) -> None:
    """
    Record the whole result, for a command whose result is one object rather
    than an array of outcomes.
    """
    global _DOCUMENT, _HAS_DOCUMENT
    _DOCUMENT = document
    _HAS_DOCUMENT = True


def json_requested() -> bool:
    """
    Whether '--json' was given: for work done only to build the result, such
    as listing a directory's files to record each one, which is not worth
    doing when nothing will print it.
    """
    return bool(ARGS_PARSER.json_output)


def any_failed() -> bool:
    """
    Whether any recorded item's 'outcome' or 'action' is 'failed', regardless
    of '--json': the wrapper exits non-zero on this even when main() itself
    raised nothing, since the command handled the error itself and recorded
    it.
    """
    return any(
        isinstance(item, dict)
        and (item.get("outcome") == "failed" or item.get("action") == "failed")
        for item in _ITEMS
    )


def results_are_streamed() -> None:
    """
    Declare that the command writes its '--json' output as it goes -- yd-follow,
    whose '--json' prints each event -- so that flush_results() prints nothing
    after it, not even the empty array a command that printed nothing gets.
    """
    global _STREAMED
    _STREAMED = True


def lower_camel_case(heading: str) -> str:
    """
    A table's column heading as a JSON key: 'Worker Pool Match?' becomes
    'workerPoolMatch', 'Node ID' 'nodeId'. Punctuation is dropped and each
    word after the first is capitalised, the rest of it lower-cased.
    """
    words = re.findall(r"[A-Za-z0-9]+", heading)
    return "".join(
        word.lower() if i == 0 else word[0].upper() + word[1:].lower()
        for i, word in enumerate(words)
    )


def rows_as_objects(headers: list[str], rows: list[list[Any]]) -> list[dict]:
    """
    A table as an array of row objects, keyed by its column headings in
    lowerCamelCase. A column with no heading -- a row number -- is dropped.
    """
    keys = [lower_camel_case(heading) for heading in headers]
    return [{key: value for key, value in zip(keys, row) if key} for row in rows]


def flush_results() -> None:
    """
    Under '--json', print the result once: the recorded document, else the
    recorded items as an array (an empty one when nothing was recorded, so
    stdout always holds a document). Otherwise print nothing.

    A command that prints its own JSON document through print_json() --
    yd-show, yd-variables, yd-doctor, yd-list -- gets no flush: its document
    is the result. JSON printed any other way would still get a trailing
    '[]'. A command that both prints its own document and records is a
    mistake in the command, and raises rather than printing a second one.
    """
    global _FLUSHED
    if _FLUSHED or not ARGS_PARSER.json_output:
        return
    _FLUSHED = True

    if _STREAMED:
        if _HAS_DOCUMENT or _ITEMS:
            raise RuntimeError(
                "The command streamed its JSON output and also recorded"
                " results; under '--json' it must do one or the other"
            )
        return

    if json_document_printed():
        if _HAS_DOCUMENT or _ITEMS:
            raise RuntimeError(
                "The command printed its own JSON document and also recorded"
                " results; under '--json' it must do one or the other"
            )
        return

    if _HAS_DOCUMENT:
        print_json(
            _DOCUMENT if isinstance(_DOCUMENT, (dict, list)) else Json.dump(_DOCUMENT)
        )
        return

    # Dicts pass through; SDK objects are serialised; '--strip-ids' applies
    print_objects_as_json(list(_ITEMS))


def flush_results_after_failure() -> None:
    """
    flush_results() for a wrapper's failure path, whose exit code is already
    decided: a flush that fails too is reported, and never replaces that
    exit code or escapes as a traceback.
    """
    try:
        flush_results()
    except Exception as e:
        print_error(f"Unable to print the results as JSON: {e}")


def reset_results() -> None:
    """
    Forget everything recorded and flushed (for tests).
    """
    global _DOCUMENT, _HAS_DOCUMENT, _FLUSHED, _STREAMED
    _ITEMS.clear()
    _DOCUMENT_PARTS.clear()
    _DOCUMENT = None
    _HAS_DOCUMENT = False
    _FLUSHED = False
    _STREAMED = False
    reset_json_document_printed()
