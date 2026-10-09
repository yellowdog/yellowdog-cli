"""
Variable substitution in files: the JSON, Jsonnet and TOML specification
loaders, and the text passes over a file's contents -- User Data, Task Data
and writeFile content files, and a Jsonnet file before it is evaluated, whose
strings and comments _substitute_jsonnet_pass() lexes so that each value is
written back with its string's escaping. The substitution engine, the
variable table and the undefined-variable warnings are
variable_substitution.py's.
"""

import os
import re
import sys
from bisect import bisect_right
from copy import deepcopy
from json import JSONDecodeError
from json import dumps as json_dumps
from json import loads as json_loads
from typing import Any, cast

from tomli import load as toml_load

from yellowdog_cli.utils.check_imports import check_jsonnet_import
from yellowdog_cli.utils.limits import VAR_SUBSTITUTION_MAX_PASSES
from yellowdog_cli.utils.misc_utils import (
    find_delimited_expression_spans,
    find_delimited_expressions,
)
from yellowdog_cli.utils.output_settings import OUTPUT
from yellowdog_cli.utils.printing import (
    print_dry_run,
    print_json,
)
from yellowdog_cli.utils.property_names import (
    COMMON_SECTION,
    VARIABLES,
)
from yellowdog_cli.utils.results import record
from yellowdog_cli.utils.variable_substitution import (
    _UNSET,
    TYPE_TAGS,
    _list_paths,
    _stringify,
    _undefined_unless_circular,
    _unsubstituted_references,
    add_substitutions_from_config_file,
    process_variable_substitutions,
    resolve_variables_insitu,
    typed_value_as_text,
)
from yellowdog_cli.utils.variable_syntax import (
    VAR_CLOSING_DELIMITER,
    VAR_OPENING_DELIMITER,
)


def load_json_file_with_variable_substitutions(
    filename: str, prefix: str = "", postfix: str = ""
) -> dict:
    """
    Takes a JSON filename and returns a dictionary with its variable
    substitutions processed.

    The file is parsed first and its values substituted after, as a TOML
    file's are, rather than its text substituted before it is parsed: there a
    value was read through JSON's escapes (a default's '\\"' was not a
    quote) and inserted without them (a Windows path's '\\t' became a tab,
    a quote ended the string). So a substitution goes inside a JSON string,
    and in a value, not a property name.
    """
    result = parse_json_file(filename, prefix, postfix)
    resolve_variables_insitu(result, prefix=prefix, postfix=postfix)
    return result


def parse_json_file(filename: str, prefix: str = "", postfix: str = "") -> Any:
    """
    A JSON specification parsed, with no substitution made yet: a parse
    error names the file (with a hint when an unquoted substitution caused
    it), and a substitution in a property name is refused, since
    substitutions are made in values only. Shared with the CSV loader,
    which expands the Tasks before substituting.
    """
    opening = prefix + VAR_OPENING_DELIMITER
    closing = VAR_CLOSING_DELIMITER + postfix
    with open(filename, encoding="utf-8") as f:
        file_contents = f.read()
    try:
        result = json_loads(file_contents)
    except JSONDecodeError as e:
        # The parser stops within the opening delimiter of one that is not
        # inside a string: at its first brace, or after it, taken for an object
        around_error = file_contents[
            max(0, e.pos - len(opening) + 1) : e.pos + len(opening)
        ]
        hint = (
            "; a variable substitution must be inside a JSON string,"
            f' e.g. "{opening}num:count{closing}"'
            if opening in around_error
            else ""
        )
        raise ValueError(f"Invalid JSON in '{filename}': {e}{hint}") from e

    _check_document(result, filename)
    names = _substituted_property_names(result, opening, closing)
    if names:
        raise ValueError(
            "Variable substitutions are made in property values, not property"
            f" names, in '{filename}': {_list_paths(names)}"
        )
    return result


def _check_document(document: object, filename: str) -> None:
    """
    Refuse a specification document that is neither an object nor a list
    (a bare number, say), naming the file, before anything walks it.
    """
    if not isinstance(document, (dict, list)):
        kind = (
            "null"
            if document is None
            else "a boolean"
            if isinstance(document, bool)
            else "a number"
            if isinstance(document, (int, float))
            else "a string"
            if isinstance(document, str)
            else type(document).__name__
        )
        raise ValueError(
            f"'{filename}' holds {kind}, not a specification (an object, or a"
            " list of them)"
        )


def _substituted_property_names(
    data: dict | list, opening_delimiter: str, closing_delimiter: str, path: str = ""
) -> list[str]:
    """
    The paths of the property names in 'data' that hold a substitution.
    """
    found: list[str] = []
    if isinstance(data, dict):
        children = []
        for key, value in data.items():
            key_path = f"{path}.{key}" if path else key
            if find_delimited_expressions(key, opening_delimiter, closing_delimiter):
                found.append(key_path)
            children.append((key_path, value))
    else:
        children = [(f"{path}[{index}]", item) for index, item in enumerate(data)]
    for child_path, child in children:
        if isinstance(child, (dict, list)):
            found += _substituted_property_names(
                child, opening_delimiter, closing_delimiter, child_path
            )
    return found


def load_jsonnet_file_with_variable_substitutions(
    filename: str,
    prefix: str = "",
    postfix: str = "",
    exit_on_dry_run=True,
    dry_run: bool = False,
) -> dict:
    """
    Takes a Jsonnet filename and returns a dictionary with its variable
    substitutions processed. With 'dry_run' ('--jsonnet-dry-run'), the
    result is printed (or recorded, under '--json', by a caller converting
    several files), and the command exits if 'exit_on_dry_run'.
    """
    check_jsonnet_import()
    from _jsonnet import evaluate_snippet

    # Jsonnet source is UTF-8, whatever the platform's default encoding
    with open(filename, encoding="utf-8") as f:
        file_contents = process_variable_substitutions_in_file_contents(
            f.read(), prefix, postfix, source=filename, jsonnet=True
        )
    # Evaluated as the file it came from, with nothing written to disk: its
    # imports are found beside it, an error names it, and the current
    # directory, the fallback for an import written relative to it, need not
    # be writable
    try:
        dict_data = json_loads(
            evaluate_snippet(filename, file_contents, jpathdir=[os.getcwd()])
        )
    except RuntimeError as e:
        raise RuntimeError(_jsonnet_error(str(e))) from e

    _check_document(dict_data, filename)

    # Secondary processing after Jsonnet expansion
    resolve_variables_insitu(dict_data, prefix=prefix, postfix=postfix)

    if dry_run:
        print_dry_run(f"Printing Jsonnet to JSON conversion for '{filename}'")
        if OUTPUT.json_output and not exit_on_dry_run:
            # A caller converting several files (yd-create, yd-remove): each
            # is one element of the '--json' document, printed at exit; a
            # copy, as the caller goes on to change what it was handed
            record(deepcopy(dict_data))
        else:
            print_json(dict_data)
        print_dry_run("Complete")
        if exit_on_dry_run:
            sys.exit(0)

    return dict_data


def _jsonnet_error(message: str) -> str:
    """
    A Jsonnet error as one line: its first, with the first location line
    added when the first has none. A static error names its place on its
    first line ('STATIC ERROR: f.jsonnet:2:9: ...'); a runtime error puts
    its message there and its place on the next ('RUNTIME ERROR: boom',
    then 'f.jsonnet:3:6-18 ...'), which alone would say what, not where.
    """
    lines = [line.strip() for line in message.splitlines() if line.strip()]
    if not lines:
        return message
    first = lines[0]
    if first.startswith("RUNTIME ERROR") and len(lines) > 1:
        location = lines[1].split("\t")[0].strip()
        return f"{first} ({location})"
    return first


def load_toml_file_with_variable_substitutions(
    filename: str, prefix: str = "", postfix: str = ""
) -> dict:
    """
    Takes a TOML filename and returns a dictionary with its variable
    substitutions processed.
    """
    with open(filename, "rb") as f:
        config = toml_load(f)

    # Add any variable substitutions in the TOML file before processing the
    # file as a whole
    variables = config.get(COMMON_SECTION, {}).get(VARIABLES)
    if variables is not None:
        if not isinstance(variables, dict):
            raise ValueError(
                f"'[{COMMON_SECTION}.{VARIABLES}]' in '{filename}' must be a table"
                f" of name = value, not {variables!r}"
            )
        # Convert all values to strings before adding
        add_substitutions_from_config_file(
            {
                var_name: _stringify(var_value)
                for var_name, var_value in variables.items()
            },
            source=f"'[{COMMON_SECTION}.{VARIABLES}]' in '{filename}'",
        )

    resolve_variables_insitu(config, prefix=prefix, postfix=postfix)

    return config


def process_variable_substitutions_in_file_contents(
    file_contents: str,
    prefix: str = "",
    postfix: str = "",
    source: str | None = None,
    jsonnet: bool = False,
) -> str:
    """
    Process substitutions in the raw contents of a complete file, repeating
    the pass until one changes nothing, as resolve_variables_insitu() does:
    a substituted value that itself contains a variable reference is
    resolved too, and a circular reference raises ValueError, naming
    'source' (the file) where it is given. An unset ('::') token is left in
    place, for the in-situ processing of a parsed specification to remove.

    With 'jsonnet', the contents are Jsonnet code, and each substitution is
    read and written through the escaping of the string it is in (see
    _substitute_jsonnet_pass()); otherwise they are text, substituted as it.
    """
    label = source if source is not None else "file contents"
    opening = prefix + VAR_OPENING_DELIMITER
    closing = VAR_CLOSING_DELIMITER + postfix
    for _ in range(VAR_SUBSTITUTION_MAX_PASSES):
        substituted = (
            _substitute_jsonnet_pass(file_contents, prefix, postfix)
            if jsonnet
            else _substitute_file_contents_pass(file_contents, prefix, postfix)
        )
        if substituted == file_contents:
            break
        previous, file_contents = file_contents, substituted
    else:
        # Name what is still changing: the expressions the last pass made
        changing = sorted(
            set(find_delimited_expressions(file_contents, opening, closing))
            - set(find_delimited_expressions(previous, opening, closing))
        )
        expressions = f" ({', '.join(repr(e) for e in changing)})" if changing else ""
        raise ValueError(
            "Variable substitution did not settle after"
            f" {VAR_SUBSTITUTION_MAX_PASSES} passes, which suggests a circular"
            f" variable reference, in '{label}'{expressions}"
        )

    # The Jsonnet pass leaves a type-tagged expression inside a longer string
    # for the in-situ pass to substitute as text, so one still here is not a
    # sign of a circular reference
    _undefined_unless_circular(
        [
            reference
            for reference in _unsubstituted_references(
                {label: file_contents}, prefix=prefix, postfix=postfix
            )
            if not reference[0][len(opening) :].startswith(TYPE_TAGS)
        ]
    )
    return file_contents


def _substitute_file_contents_pass(
    file_contents: str, prefix: str = "", postfix: str = ""
) -> str:
    """
    One substitution pass over the raw contents of a complete file.
    """
    # Found one expression at a time: a match running from the first opening
    # delimiter on a line to the last closing one took every expression on
    # the line as one, which lost a type-tagged value's type and, where the
    # line went on to close a JSON object ('}}'), failed on the delimiters
    v_expressions = dict.fromkeys(
        find_delimited_expressions(
            file_contents,
            prefix + VAR_OPENING_DELIMITER,
            VAR_CLOSING_DELIMITER + postfix,
        )
    )

    for v_expression in v_expressions:
        replacement_expression = process_variable_substitutions(
            v_expression, prefix=prefix, postfix=postfix
        )
        if replacement_expression is _UNSET:
            continue  # leave the token intact; dict-level processing will remove the key
        if isinstance(replacement_expression, str):
            file_contents = file_contents.replace(v_expression, replacement_expression)
        else:
            # A number, a boolean, a table or an array. Inside quotes, the
            # quotes go with it, so that a JSON or Jsonnet string becomes the
            # value itself (both quote styles, for Jsonnet); anywhere else --
            # a shell script's 'N={{num:count}}' -- it is text, written as a
            # typed expression within a longer string is, where it used to be
            # left as it was, neither substituted nor warned of. Either way a
            # number keeps the form it was written in ('1.10' stays '1.10'),
            # and the rest are their JSON ('true', double quotes)
            opening = prefix + VAR_OPENING_DELIMITER
            type_tag = next(
                tag for tag in TYPE_TAGS if v_expression[len(opening) :].startswith(tag)
            )
            as_written = process_variable_substitutions(
                opening + v_expression[len(opening) + len(type_tag) :],
                prefix=prefix,
                postfix=postfix,
            )
            replacement = typed_value_as_text(
                type_tag,
                cast(int | bool | float | list | dict, replacement_expression),
                cast(str, as_written),
            )
            file_contents = file_contents.replace(f'"{v_expression}"', replacement)
            file_contents = file_contents.replace(f"'{v_expression}'", replacement)
            file_contents = file_contents.replace(v_expression, replacement)

    return file_contents


# Jsonnet's string literals, each with the group its contents are in, and its
# comments, matched only so that a quote inside one opens no string. A text
# block's contents run from the line after its '|||' to the line before the
# one closing it
_JSONNET_LITERAL = re.compile(
    r"//[^\n]*|\#[^\n]*|/\*.*?\*/"
    r'|@"(?P<verbatim_double>(?:[^"]|"")*)"'
    r"|@'(?P<verbatim_single>(?:[^']|'')*)'"
    r'|"(?P<double>(?:[^"\\]|\\.)*)"'
    r"|'(?P<single>(?:[^'\\]|\\.)*)'"
    r"|\|\|\|-?[ \t]*\n(?P<block>.*?\n)[ \t]*\|\|\|",
    re.DOTALL,
)


# A text block's indentation, read from its first line
_INDENTATION = re.compile(r"[ \t]*")


# A double- or single-quoted string's escapes: JSON's, with '\\'' too
_JSONNET_ESCAPE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.DOTALL)


_JSONNET_ESCAPED = {
    '"': '"',
    "'": "'",
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


def _jsonnet_unescaped(kind: str, text: str) -> str:
    """
    Text from inside a Jsonnet string of the given kind, as what it stands for.
    """
    match kind:
        case "double" | "single":
            return _JSONNET_ESCAPE.sub(
                lambda m: (
                    chr(int(m[1][1:], 16))
                    if len(m[1]) == 5
                    else _JSONNET_ESCAPED.get(m[1], m[0])
                ),
                text,
            )
        case "verbatim_double":
            return text.replace('""', '"')
        case "verbatim_single":
            return text.replace("''", "'")
    return text  # A text block has no escapes


def _jsonnet_escaped(kind: str, text: str, indentation: str) -> str:
    """
    Text written for a Jsonnet string of the given kind: escaped, or in a
    text block indented as the block is on every line after its first.
    """
    match kind:
        case "double":
            return json_dumps(text)[1:-1]
        case "single":
            return json_dumps(text)[1:-1].replace("'", "\\'")
        case "verbatim_double":
            return text.replace('"', '""')
        case "verbatim_single":
            return text.replace("'", "''")
    return text.replace("\n", "\n" + indentation)


def _substitute_jsonnet_pass(
    file_contents: str, prefix: str = "", postfix: str = ""
) -> str:
    """
    One substitution pass over the code of a Jsonnet file, which is evaluated
    only once it is substituted, so it is the text that is substituted: each
    expression by its position, since what is written depends on where it is.

    Inside a string, an expression is read through the string's escapes and
    its value written back with them, so a path's backslashes, a quote, and a
    default's escaped JSON ('[\\"x\\"]') are themselves. A typed value is
    written as its JSON in place of the whole string when the expression is
    all of it, and otherwise left for the in-situ pass after evaluation to
    substitute as text, as the text pass leaves one. Outside a string, in the
    code, a value is written as it is, a typed one as its JSON: Jsonnet code.
    """
    opening = prefix + VAR_OPENING_DELIMITER
    closing = VAR_CLOSING_DELIMITER + postfix
    strings = [
        (
            match.lastgroup,
            match.start(match.lastgroup),
            match.end(match.lastgroup),
            match,
        )
        for match in _JSONNET_LITERAL.finditer(file_contents)
        if match.lastgroup is not None  # Not a comment
    ]
    starts = [start for _, start, _, _ in strings]

    # Substituted once each per pass, however often it appears: an expression
    # as written, with the kind of string it is in (None in the code)
    values: dict[tuple[str | None, str], object] = {}
    parts: list[str] = []
    position = 0
    for span in find_delimited_expression_spans(file_contents, opening, closing):
        if span.start < position:
            continue  # Inside a whole string already written as its value
        index = bisect_right(starts, span.start) - 1
        kind, content_start, content_end, literal = (
            strings[index] if index >= 0 else (None, 0, 0, None)
        )
        if kind is None or span.end > content_end:
            kind = None  # In the code, or across a string's end
        as_written = file_contents[span.start : span.end]
        expression = (
            _jsonnet_unescaped(kind, as_written) if kind is not None else as_written
        )
        if (kind, as_written) not in values:
            values[(kind, as_written)] = process_variable_substitutions(
                expression, prefix=prefix, postfix=postfix
            )
        value = values[(kind, as_written)]

        if value is _UNSET or value == expression:
            # Left as it is: the in-situ pass removes an unset one's property
            continue
        if kind is None:
            written = value if isinstance(value, str) else json_dumps(value)
            start, end = span.start, span.end
        elif isinstance(value, str):
            indentation = (
                _INDENTATION.match(file_contents, content_start).group()  # type: ignore[union-attr]
                if kind == "block"
                else ""
            )
            written = _jsonnet_escaped(kind, value, indentation)
            start, end = span.start, span.end
        elif (span.start, span.end) == (content_start, content_end) and kind != "block":
            assert literal is not None
            written = json_dumps(value)
            start, end = literal.start(), literal.end()
        else:
            continue
        parts += [file_contents[position:start], written]
        position = end

    parts.append(file_contents[position:])
    return "".join(parts)
