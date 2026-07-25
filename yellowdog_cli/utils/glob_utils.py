"""
Glob primitives shared across the CLI. Dependency-free leaf module.
"""

GLOB_CHARS = frozenset("*?[")


def contains_glob_chars(name: str) -> bool:
    """
    Return True if 'name' contains a glob metacharacter (* ? [). Whole-string
    check — for matching entity names/IDs, which never legitimately contain a
    colon-prefixed component. (rclone remote paths use dataclient_utils.is_glob,
    which strips a leading 'remote:' prefix first.)
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
