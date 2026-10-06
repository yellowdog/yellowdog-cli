"""
The variable substitution syntax: delimiters, type tags, the rules for a
variable's name, the names the CLI reserves or defines lazily, and the names
'yd-variables' redacts as looking like credentials.
"""

import re

ENV_VAR_SUB_PREFIX = "env:"

# Widths, in base 36 digits, of the '{{random}}' and '{{random6}}' variables
RAND_VAR_DIGITS = 3
RAND_VAR_6_DIGITS = 6

# Delimiters: Worker Pool User Data's, CSV prototypes', and the specifications'
WP_VARIABLES_PREFIX = "__"
WP_VARIABLES_POSTFIX = "__"
CSV_VAR_OPENING_DELIMITER = "<<"
CSV_VAR_CLOSING_DELIMITER = ">>"
VAR_OPENING_DELIMITER = "{{"
VAR_CLOSING_DELIMITER = "}}"
VAR_DEFAULT_SEPARATOR = ":="
VAR_UNSET_SUFFIX = "::"

# A variable name: a letter, digit or '_', then letters, digits, '_', '.' and
# '-'. Enforced wherever a variable is defined, and what decides whether a
# '{{...}}' expression refers to a variable at all: one that breaks it (Docker's
# '{{.ID}}', Go's '{{- .Values }}') is text. '.' and '-' may not come first for
# that reason. The rule rules out the substitution syntax ('}}', ':=', '::', a
# type tag's ':') by construction.
VARIABLE_NAME_PATTERN = r"[A-Za-z0-9_][A-Za-z0-9_.-]*"
VARIABLE_NAME_RULE = (
    "a name must start with a letter, digit or '_', and contain only letters,"
    " digits, '_', '.' and '-'"
)
# Variables the CLI defines itself from its configuration ('[common]', the
# YD_* environment variables, the options), mapped to where each is set. They
# are not user variables: defined as one, only '{{name}}' would change, not the
# namespace, tag or credentials the command acts on -- and one unset with
# '{{::}}' would simply be defined again from the configuration -- so each is an
# error wherever a user variable is defined
RESERVED_VARIABLE_NAMES = {
    "namespace": "'namespace' in '[common]', 'YD_NAMESPACE' or '--namespace'",
    "tag": "'tag' in '[common]', 'YD_TAG' or '--tag'",
    "key": "'key' in '[common]', 'YD_KEY' or '--key'",
    "secret": "'secret' in '[common]', 'YD_SECRET' or '--secret'",
    "url": "'url' in '[common]', 'YD_URL' or '--url'",
}
# An 'env:' name belongs to the operating system rather than to us (Windows has
# 'ProgramFiles(x86)'), so it may hold anything but whitespace and the syntax
ENV_VARIABLE_NAME_PATTERN = r"[^\s{}:=]+"

# Lazy variable substitution names (used in submit/task naming)
L_WR_NAME = "wr_name"
L_TASK_NAME = "task_name"
L_TASK_NUMBER = "task_number"
L_TASK_GROUP_NAME = "task_group_name"
L_TASK_GROUP_NUMBER = "task_group_number"
L_TASK_COUNT = "task_count"
L_TASK_GROUP_COUNT = "task_group_count"
LAZY_VARIABLE_NAMES = (
    L_WR_NAME,
    L_TASK_NAME,
    L_TASK_NUMBER,
    L_TASK_GROUP_NAME,
    L_TASK_GROUP_NUMBER,
    L_TASK_COUNT,
    L_TASK_GROUP_COUNT,
)
VAR_NAME_OF_UNNAMED_TASK = "none"

# Type tags
TYPE_TAG_TERMINATOR = ":"
# The character(s) of VAR_DEFAULT_SEPARATOR that follow TYPE_TAG_TERMINATOR.
# Used as a negative lookahead in the type-tag regex: after matching e.g. 'num:',
# if this follows, the ':' is part of ':=' (a default separator), not a type tag.
TYPE_TAG_DEFAULT_GUARD = VAR_DEFAULT_SEPARATOR[len(TYPE_TAG_TERMINATOR) :]
NUMBER_TYPE_TAG = "num" + TYPE_TAG_TERMINATOR
BOOL_TYPE_TAG = "bool" + TYPE_TAG_TERMINATOR
ARRAY_TYPE_TAG = "array" + TYPE_TAG_TERMINATOR
TABLE_TYPE_TAG = "table" + TYPE_TAG_TERMINATOR
FORMAT_NAME_TYPE_TAG = "format_name" + TYPE_TAG_TERMINATOR

# The names of user-defined variables that 'yd-variables' redacts in its full
# report, as looking like credentials (searched for anywhere in the name). A
# heuristic, and stated as one: the command prints this pattern whenever it
# redacts by it. 'key' alone is deliberately absent: 'APP_KEY_DEMO' is an
# identifier, not a secret
SECRET_VARIABLE_NAME_PATTERN = re.compile(
    r"secret|password|passwd|token|credential|private_key", re.IGNORECASE
)
