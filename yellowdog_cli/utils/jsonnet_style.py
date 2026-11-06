"""
JSON text rewritten in the style of a hand-written Jsonnet file, for an
'--output-file' named '.jsonnet': a key unquoted where it is an identifier,
a string in single quotes unless it holds one, and a trailing comma after
the last element of a multi-line object or array. JSON is already Jsonnet,
so this changes only how the file looks, never what it evaluates to.

It works on the text the compact JSON encoder writes, a token at a time,
since a JSON string holds no raw newline and so never spans lines. Stdlib
only.
"""

import re

# A JSON string literal, as the encoder writes it
_JSON_STRING = re.compile(r'"(?:[^"\\]|\\.)*"')
_ESCAPE = re.compile(r"\\(.)")
_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_KEY_FOLLOWS = re.compile(r"\s*:")

# Jsonnet's reserved words, which a key may not be unquoted
JSONNET_KEYWORDS = frozenset(
    {
        "assert",
        "else",
        "error",
        "false",
        "for",
        "function",
        "if",
        "import",
        "importbin",
        "importstr",
        "in",
        "local",
        "null",
        "self",
        "super",
        "tailstrict",
        "then",
        "true",
    }
)

JSONNET_EXTENSION = ".jsonnet"


def is_jsonnet_path(path: str) -> bool:
    """
    Whether a file written to 'path' is to be in the Jsonnet style: its
    extension is '.jsonnet', in any case.
    """
    return path.lower().endswith(JSONNET_EXTENSION)


def jsonnet_style(json_text: str) -> str:
    """
    'json_text', a JSON document or a run of its lines, in the Jsonnet
    style.
    """
    lines = [_rewritten_line(line) for line in json_text.split("\n")]
    for index, line in enumerate(lines[:-1]):
        following = lines[index + 1].lstrip()
        if (
            following[:1] in ("}", "]")
            and line.strip()
            and not line.endswith((",", "{", "["))
        ):
            lines[index] = line + ","
    return "\n".join(lines)


def _rewritten_line(line: str) -> str:
    parts: list[str] = []
    position = 0
    for match in _JSON_STRING.finditer(line):
        parts.append(line[position : match.start()])
        is_key = _KEY_FOLLOWS.match(line, match.end()) is not None
        parts.append(_jsonnet_string(match.group(0), is_key))
        position = match.end()
    parts.append(line[position:])
    return "".join(parts)


def _jsonnet_string(literal: str, is_key: bool) -> str:
    """
    A JSON string literal as Jsonnet writes it: bare as a key that is an
    identifier, else in single quotes unless it holds one. Jsonnet takes
    JSON's escapes in either quotes, so only the quote itself changes: an
    escaped double quote needs no escape between single quotes.
    """
    body = literal[1:-1]
    if is_key and _IDENTIFIER.fullmatch(body) and body not in JSONNET_KEYWORDS:
        return body
    if "'" in body:
        return literal
    return "'" + _ESCAPE.sub(_unescaped_double_quote, body) + "'"


def _unescaped_double_quote(match: re.Match[str]) -> str:
    return '"' if match.group(1) == '"' else match.group(0)
