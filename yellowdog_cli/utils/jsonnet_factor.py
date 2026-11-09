"""
A flat list of specifications factored into Jsonnet ('yd jsonnet factor'):
one 'local' base per kind of specification, holding the value most of its
members give each property, and each specification written as that base
extended by its differences ('awsInstances { source+: { name: ... } }').

The kind is the specification's 'resource' and the 'type' of it or its
'source' (a Compute Source Template's provider). A base holds a property
that at least BASE_SHARE of its kind's members set, at the value most of
them give it, where two or more do; an object-valued property is a base
of its own, merged into ('source+:'). A member that differs overrides the
value; one that lacks a property the base holds hides it ('key:: null', a
hidden field being left out of the output), in the specification and its
'source' only: deeper, an object that lacks one is written whole, which
reads more plainly than a hidden field inside a merge.

It finds what is shared, not why: a series a person would write as a loop
is still written out member by member. The text is checked by evaluating
it (factored_and_checked()), so a factoring that would change what the
file means is never written. Stdlib only, bar that check's Jsonnet.
"""

import json
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Any

from yellowdog_cli.utils.compact_json import (
    CompactJSONEncoder,
    FloatAsWritten,
    IntAsWritten,
)
from yellowdog_cli.utils.jsonnet_style import JSONNET_KEYWORDS, jsonnet_style
from yellowdog_cli.utils.property_names import (
    PROP_RESOURCE,
    PROP_SOURCE,
    PROP_TYPE,
)

# The share of a kind's members that must set a property for its base to
# hold it; the rest hide it
BASE_SHARE = 0.8
INDENT = "  "
# The longest line a member's differences are written on whole
INLINE_WIDTH = 80
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The properties a member hides only at these depths: the specification
# and its source
_HIDING_DEPTH = 1


class FactoringError(Exception):
    """
    The factored text does not evaluate to the specifications it was made
    from: a fault in the factoring, so nothing is written.
    """


class _Op(Enum):
    SET = ":"  # The value replaces the base's
    MERGE = "+:"  # An object merged into the base's
    HIDE = "::"  # The base's property left out


@dataclass(frozen=True)
class _Field:
    key: str
    op: _Op
    value: Any = None


def factored(specifications: list) -> str:
    """
    'specifications' as Jsonnet, each kind with two or more members written
    as a base and its members' differences. Anything that is not an object
    is written as it is.
    """
    groups: dict[str, list[int]] = defaultdict(list)
    for index, specification in enumerate(specifications):
        if isinstance(specification, dict):
            groups[_kind(specification)].append(index)

    bases: list[str] = []
    items = [_text(item, 1) for item in specifications]
    taken: set[str] = set()
    for kind, indexes in groups.items():
        members = [specifications[i] for i in indexes]
        base = _base(members) if len(members) > 1 else {}
        if not base:
            continue
        name = _local_name(kind, taken)
        bases.append(f"local {name} = {_text(base, 0)};\n\n")
        for i in indexes:
            fields = _difference(specifications[i], base, depth=0)
            items[i] = f"{name} {_object_text(fields, 1)}" if fields else name
    body = "".join(f"{INDENT}{item},\n" for item in items)
    return "".join(bases) + ("[\n" + body + "]\n" if items else "[]\n")


def factored_and_checked(specifications: list) -> str:
    """
    factored(), evaluated to make sure it gives back 'specifications':
    FactoringError if it does not. Needs the 'jsonnet' extra.
    """
    from _jsonnet import evaluate_snippet

    text = factored(specifications)
    if json.loads(evaluate_snippet("factored.jsonnet", text)) != specifications:
        raise FactoringError(
            "the factored Jsonnet would not evaluate to the same JSON, so it was"
            " not written"
        )
    return text


def _kind(specification: dict) -> str:
    source = specification.get(PROP_SOURCE)
    source_type = source.get(PROP_TYPE) if isinstance(source, dict) else None
    return "|".join(
        str(part)
        for part in (
            specification.get(PROP_RESOURCE),
            specification.get(PROP_TYPE),
            source_type,
        )
        if part is not None
    )


def _base(objects: list[dict]) -> dict:
    """
    Each property at least BASE_SHARE of 'objects' set, at the value most
    of them give it (the first given, in a tie) where two or more give it;
    for one that is an object in every holder and not the same in all, its
    own base.
    """
    base: dict = {}
    for key in dict.fromkeys(key for o in objects for key in o):
        holders = [o for o in objects if key in o]
        if len(holders) < max(2, BASE_SHARE * len(objects)):
            continue
        values = [o[key] for o in holders]
        if all(isinstance(v, dict) for v in values) and any(
            not _same(v, values[0]) for v in values
        ):
            inner = _base(values)
            if inner:
                base[key] = inner
            continue
        counts: dict[str, list] = {}
        for value in values:
            counts.setdefault(_identity(value), [value, 0])[1] += 1
        value, count = max(counts.values(), key=lambda vc: vc[1])
        if count >= 2:
            base[key] = value
    return base


def _difference(item: dict, base: dict, depth: int) -> list[_Field] | None:
    """
    The fields that make 'base' into 'item', or None where 'item' lacks a
    property the base holds and is too deep to hide it in.
    """
    missing = [key for key in base if key not in item]
    if missing and depth > _HIDING_DEPTH:
        return None
    fields = [_Field(key, _Op.HIDE) for key in missing]
    for key, value in item.items():
        if key not in base:
            fields.append(_Field(key, _Op.SET, value))
        elif _same(base[key], value):
            continue
        elif isinstance(value, dict) and isinstance(base[key], dict):
            inner = _difference(value, base[key], depth + 1)
            fields.append(
                _Field(key, _Op.SET, value)
                if inner is None
                else _Field(key, _Op.MERGE, inner)
            )
        else:
            fields.append(_Field(key, _Op.SET, value))
    return fields


def _same(a: Any, b: Any) -> bool:
    return _identity(a) == _identity(b)


def _identity(value: Any) -> str:
    """
    'value' as text that two values share only if they are written the
    same: a number read as written ('1.10') is not the same as '1.1', since
    the factored file must write each as it was.
    """
    return json.dumps(_written(value), sort_keys=True)


def _written(value: Any) -> Any:
    if isinstance(value, (FloatAsWritten, IntAsWritten)):
        return {"\u0000number": value.text}
    if isinstance(value, dict):
        return {key: _written(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_written(item) for item in value]
    return value


def _object_text(fields: list[_Field], depth: int) -> str:
    """
    The fields as an object: on one line where they fit, as the compact
    encoder writes a short object, else one field to a line.
    """
    pad = INDENT * (depth + 1)
    entries = []
    for field in fields:
        if field.op is _Op.HIDE:
            value = "null"
        elif field.op is _Op.MERGE:
            value = _object_text(field.value, depth + 1)
        else:
            value = _text(field.value, depth + 1)
        entries.append(f"{_field_name(field.key)}{field.op.value} {value}")
    inline = "{" + ", ".join(entries) + "}"
    if "\n" not in inline and len(pad) + len(inline) <= INLINE_WIDTH:
        return inline
    lines = [f"{pad}{entry}," for entry in entries]
    return "{\n" + "\n".join(lines) + "\n" + INDENT * depth + "}"


def _field_name(key: str) -> str:
    if _IDENTIFIER.fullmatch(key) and key not in JSONNET_KEYWORDS:
        return key
    return jsonnet_style(json.dumps(key))


def _text(value: Any, depth: int) -> str:
    """
    A plain value in the Jsonnet style, its lines after the first indented
    to 'depth'.
    """
    text = jsonnet_style(
        json.dumps(
            value, indent=len(INDENT), cls=CompactJSONEncoder, ensure_ascii=False
        )
    )
    return text.replace("\n", "\n" + INDENT * depth)


def _local_name(kind: str, taken: set[str]) -> str:
    """
    A name for a kind's base, from its most specific part:
    'co.yellowdog.platform.model.AwsInstancesComputeSource' is awsInstances.
    """
    last = kind.rsplit("|", 1)[-1].rsplit(".", 1)[-1].removesuffix("ComputeSource")
    words = re.sub(r"[^A-Za-z0-9]+", " ", last).split()
    name = "".join(w[:1].upper() + w[1:] for w in words) or "base"
    name = name[:1].lower() + name[1:]
    if not _IDENTIFIER.fullmatch(name) or name in JSONNET_KEYWORDS:
        name = "base" + name[:1].upper() + name[1:]
    candidate, number = name, 2
    while candidate in taken:
        candidate, number = f"{name}{number}", number + 1
    taken.add(candidate)
    return candidate
