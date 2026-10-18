"""
Glob primitives shared across the CLI. Dependency-free leaf module.
"""

GLOB_CHARS = frozenset("*?[")


def contains_glob_chars(name: str) -> bool:
    """
    Return True if 'name' contains a glob metacharacter (* ? [). Whole-string
    check — for matching entity names/IDs, which never legitimately contain a
    colon-prefixed component. (rclone remote paths use
    dataclient.operations.is_glob, which strips a leading 'remote:' prefix
    first.)
    """
    return bool(GLOB_CHARS.intersection(name))


def glob_search_prefix(pattern: str) -> str:
    """
    Return the longest leading substring of 'pattern' before the first glob
    metacharacter (* ? [). Empty string if the pattern starts with one. Used
    as a partial-name hint for server-side searches before local fnmatch.
    """
    prefix: list[str] = []
    for char in pattern:
        if char in GLOB_CHARS:
            break
        prefix.append(char)
    return "".join(prefix)


def glob_literal_hint(pattern: str) -> str:
    """
    Return the longest run of literal characters in 'pattern', outside any
    '[...]' class and between the metacharacters: a substring every name the
    glob matches contains, so a hint for a server-side substring search
    before local fnmatch, which narrows even a pattern with no literal
    prefix ('*-1'). Empty string if there is none.
    """
    runs: list[str] = []
    current: list[str] = []
    in_class = False
    for char in pattern:
        if in_class:
            in_class = char != "]"
            continue
        if char in GLOB_CHARS:
            runs.append("".join(current))
            current = []
            in_class = char == "["
            continue
        current.append(char)
    runs.append("".join(current))
    return max(runs, key=len)
