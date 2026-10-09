# Variable Substitutions

<!--ts-->
   * [Default Variables](#default-variables)
   * [User-Defined Variables](#user-defined-variables)
      * [Variable Naming](#variable-naming)
      * [Setting Variable Values](#setting-variable-values)
      * [Precedence Order](#precedence-order)
      * [Nested Variables](#nested-variables)
      * [Providing Default Values for User-Defined Variables](#providing-default-values-for-user-defined-variables)
      * [Removing Properties Using the Unset Suffix](#removing-properties-using-the-unset-suffix)
      * [Undefined Variables](#undefined-variables)
   * [Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data](#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 10:46:48 BST 2026 -->

<!--te-->


Variable substitutions provide a powerful mechanism for introducing variable values into TOML configuration files, and JSON/Jsonnet definitions. They can be included in the value of any property in any of these objects, including in values within arrays (lists), e.g. for the `arguments` property, and tables (dictionaries), e.g. the `environment` property. In a JSON file a substitution is written inside a string, as `"{{num:count}}"` rather than `{{num:count}}`, even for a number, table or array, and never in a property name; the value it gives is substituted as it is, so a Windows path or a quotation mark needs no escaping. A Jsonnet file is more flexible: see [Variable Substitutions in Jsonnet Files](jsonnet.md#variable-substitutions-in-jsonnet-files).

Variable substitutions are expressed using the `{{variable}}` notation (note: no spaces between the double brackets and the variable name), where the expression is replaced by the value of `variable`.

Substitutions can also be performed for non-string (number, boolean, array, and table) values using the `num:`, `bool:`, `array:`, and `table:` prefixes within the variable substitution:

- Define the variable substitution using one of the following patterns: `"{{num:my_int}}"`, `"{{num:my_float}}"`, `"{{bool:my_bool}}"`, `"{{array:my_array}}"`, `"{{table:my_table}}"`
- Variable definitions supplied on the command line would then be of the form, e.g.:

```shell
 yd-submit -v my_int=5 -v my_float=2.5 -v my_bool=true \
           -v my_array="[1,2,3]" -v my_table='{"A": 100, "B": 200}'
```

- In the processed JSON (or TOML), these values would become `5`, `2.5`, `true`, `[1,2,3]`, and `{"A": 100, "B": 200}`, respectively, converted from strings to their correct JSON types

> **Note:** `array:` and `table:` values are JSON, with double-quoted strings and `true`/`false`/`null`, or the same in Python's spelling, with single-quoted strings and `True`/`False`/`None`, which can be easier to quote on a command line: `-v "tags=['a','b']"` rather than `-v 'tags=["a","b"]'`, and on Windows rather than `-v "tags=[\"a\",\"b\"]"`. Python's spelling is read only where the value is not JSON, and only for what JSON could hold: a table's keys must be strings, and a tuple, a set, bytes or a complex number is refused. In a TOML single-quoted (literal) string, which cannot contain a single quote, use JSON.

A `num:` value may be written in JSON's syntax or Python's, e.g. `5`, `-2.5`, `1e3`, `1E3` or `1_000`, but must be a finite number: `nan` and `inf` are refused, as they are inside an `array:` or `table:`, since JSON cannot carry them. A `bool:` value is `true` or `false` in any case, so `True` and `TRUE` are accepted too. A value that is not of its tag's type is an error naming the substitution, e.g. `Cannot substitute '{{num:count}}': 'abc' is not a number`.

A type-tagged substitution that is only part of a string, e.g. `"--retries={{num:retries}}"` or `"--tags={{array:tags}}"`, is checked as its type and then written into the string as text: a number as it was written (`1.10` stays `1.10`), and a boolean, array or table as JSON (`true`, `["a", "b"]`). The same holds in the text files substituted as a whole — User Data scripts, Task Data files and `writeFile` content files — where `N={{num:count}}` in a shell script becomes `N=5`, and one standing alone in quotes, `"{{num:count}}"`, loses its quotes, so that in a JSON file it becomes the number itself.

Every variable value is held internally as a string, whatever form it was defined in. A variable defined as something other than a string — an array, table, number or boolean, in `[common.variables]` or with `--property common.variables.<name>=<value>` — is held as its **JSON** text, so that it can be read back by the type tags; this means that `my_array = [1, 2, 3]` and `my_array = "[1,2,3]"` are equivalent definitions, as are `my_bool = true` and `my_bool = "true"`. (Note that `yd-variables` reports the stored string, so an array is reported as `"[1, 2, 3]"` rather than as a JSON array.)

## Default Variables

The following substitutions are automatically created and can be used in any section of the configuration file, or in any JSON specification:

| Directive             | Description                                                    | Example of Substitution |
|:----------------------|:---------------------------------------------------------------|:------------------------|
| `{{username}}`        | The current user's login username, lower case, spaces replaced | jane_smith              |
| `{{date}}`            | The current date (UTC): YYMMDD                                 | 221027                  |
| `{{time}}`            | The current time (UTC): HHMMSSss                               | 16302699                |
| `{{datetime}}`        | Concatenation of the date and time, with a '-' separator       | 221027-163026           |
| `{{random}}`          | Three random base 36 digits (0-9, a-z), lower case             | a1c                     |
| `{{random6}}`         | Six random base 36 digits (0-9, a-z), lower case               | a1c9z0                  |
| `{{pid}}`             | The process ID (PID) of the running command                    | 48213                   |
| `{{pid2}}`            | The process discriminator: the PID mod 1296, in two base 36 digits, lower case | 4f      |
| `{{namespace}}`       | The `namespace` property.                                      | my_namespace            |
| `{{tag}}`             | The `tag` property.                                            | my_tag                  |
| `{{key}}`             | The application `key` property.                                |                         |
| `{{secret}}`          | The application `secret` property.                             |                         |
| `{{url}}`             | The Platform `url` property.                                   |                         |
| `{{config_dir_abs}}`  | The absolute directory path of the configuration file          | /yellowdog/workloads    |
| `{{config_dir_name}}` | The immediate containing directory of the configuration file   | workloads               |

The `namespace`, `tag`, `key`, `secret` and `url` variables always hold the values the command is using, and cannot be redefined or unset as user-defined variables (see [Variable Naming](#variable-naming)); the other default variables can be overridden, as described in [Precedence Order](#precedence-order).

For the `date`, `time`, `datetime`, `random`, `random6`, `pid` and `pid2` directives, the same values will be used for the duration of a command — i.e. if `{{time}}` is used within multiple properties, the identical value will be used for each substitution.

The `config_dir_` substitutions use the name of the directory containing the nominated TOML configuration file, or the invocation directory if no configuration file is supplied.

The `random` and `random6` directives use base 36 digits rather than hexadecimal, base 36 being the widest alphabet a YellowDog name may be built from, so they carry the most randomness in the fewest characters: `random` has 46,656 possible values and `random6` has 2,176,782,336.

The `pid2` directive is the same two characters that an automatically generated name ends with (see [Naming Rules](configuration.md#naming-rules)), so a hand-written name such as `name = "{{tag}}-{{datetime}}-{{pid2}}"` is disambiguated between simultaneously launched commands in exactly the way a generated one is: processes alive at the same time always have distinct PIDs, so `{{pid2}}` differs between them unless 1,296 processes were spawned in between. The `pid` directive is the full PID, which is unambiguous but too long, and too variable in length, to sit comfortably in a name.

## User-Defined Variables

User-defined variables can be supplied using an option on the command line, by setting environment variables prefixed with `YD_VAR_`, by using general environment variables, or by including properties in the `[common]` section of the TOML configuration file.

### Variable Naming

A variable name must start with a letter, a digit or an underscore, and may contain only letters, digits, underscores (`_`), full stops (`.`) and hyphens (`-`), e.g. `project_code`, `run-2`, `9lives` or `dataClient.prod.bucket`. Names are case-sensitive. A name that breaks this rule is an error wherever the variable is defined — on the command line, in a `YD_VAR_` environment variable, in `[common.variables]`, or with `--property common.variables.<name>` — and the error names the definition.

The names `namespace`, `tag`, `key`, `secret` and `url` are reserved for the [default variables](#default-variables) that the CLI defines from its configuration, and defining a variable with one of them is an error at any of those sources. Such a variable would change only what `{{tag}}` (for example) substitutes, not the tag the command actually uses to name and select entities, and one unset with `{{::}}` would simply be defined again from the configuration. Set these values with the `[common]` properties, the `YD_NAMESPACE`, `YD_TAG`, `YD_KEY`, `YD_SECRET` and `YD_URL` environment variables, or the `--namespace`/`-n`, `--tag`/`-t`, `--key`, `--secret` and `--url` options instead, as described in [Specifying Common Properties using the Command Line or Environment Variables](configuration.md#specifying-common-properties-using-the-command-line-or-environment-variables). Names differing only in case, such as `TAG`, are not reserved.

The same rule decides what a substitution refers to: a `{{...}}` expression whose name breaks it is not a variable substitution at all, and is left as it is, which is what allows text meant for other tools, such as Docker's `{{.ID}}` or a Go template's `{{- .Values.image }}`, to pass through unchanged. This is also why a name may not start with `.` or `-`, and why there should be no spaces between a variable name and the curly brackets.

The rule excludes the substitution syntax itself (`}}`, the `:=` default-value separator and the `::` unset suffix) and the type-tag prefixes (`num:`, `bool:`, `array:`, `table:`, `format_name:`) and `env:`, which have special meaning at the start of a substitution. The exception is the name of a general environment variable in an `{{env:NAME}}` substitution, which is the operating system's to decide, and may contain anything but whitespace and the substitution syntax, e.g. `{{env:ProgramFiles(x86)}}`.

`YD_VAR_` environment variables create variable names with the **exact case** of the suffix — `YD_VAR_SUFFIX` creates `SUFFIX`, not `suffix`. On Windows, environment variable names are uppercased by the OS, so use uppercase names only.

### Setting Variable Values

1. The **command-line** option is `--variable` (or `-v`). For example, `yd-submit -v project_code=pr-213-a -v run_id=1234` will establish two new variables that can be used as `{{project_code}}` and `{{run_id}}`, which will be substituted by `pr-213-a` and `1234` respectively.


2. For **environment variables**, setting the variable `YD_VAR_project_code="pr-213-a"` will create a new variable that can be accessed as `{{project_code}}`, which will be substituted by `pr-213-a`. Note that if running on Windows, all environment variable names are case-insensitive and converted to upper case, so choose upper case variable names only.


3. **General (i.e. non-`YD_VAR_`) environment variables** can be used by adding the `env:` prefix before the name of the environment variable in the substitution, e.g. `{{env:ENV_VAR_NAME}}`. (If you also need to use one of the type prefixes, just do so as follows (e.g.): `{{num:env:COUNT}}`). A default value can also be provided for the case where the environment variable is not set: `{{env:ENV_VAR_NAME:=default_value}}`.


4. For **setting within the TOML file**, include a **`variables`** table in the `[common]` section of the file. E.g. `variables = {project_code = "pr-213a", run_id = "1234"}`. Note that this can also use the form:

```toml
[common.variables]
    project_code = "pr-213a"
    run_id = "1234"
```

TOML values that are not strings are converted to their JSON text when they're loaded, so `counts = [1, 2, 3]` can be used as `"{{array:counts}}"` exactly as `counts = "[1,2,3]"` can, and `enabled = true` substitutes as `true` rather than as Python's `True`. (TOML's date, time and datetime values have no JSON form, and are held as the text they were written as.)

### Precedence Order

The precedence order for setting variables is:

1. Command line (`--variable`/`-v`)
2. `YD_VAR_` environment variables
3. `YD_VAR_` variables defined in a `.env` file
4. TOML configuration file (`[common.variables]`)

**Exception**: if the configuration file is explicitly selected using the `--config`/`-c` option, its `[common.variables]` definitions take precedence over `YD_VAR_` environment variables (items 2 and 3), but never over variables set on the command line.

(Substitutions using the `{{env:NAME}}` syntax are resolved directly from the named environment variable at the point of use, and do not participate in this precedence order.)

This method can also be used to override some default variables, e.g. setting `-v username="other-user"` will override the default `{{username}}` variable.

### Nested Variables

Variable substitutions can be nested, in TOML, JSON and Jsonnet files alike.

For example, if one wanted to select a different `templateId` for a Worker Pool depending on the value of a `region` variable, one could use the following:

```toml
[common.variables]
    template_london = "ydid:crt:65EF4F:a4d757cf-b67a-4eb6-bd39-8a6ffd46c8f4"
    template_phoenix = "ydid:crt:65EF4F:e4239dec-78c2-421c-a7f3-71e61b72946f"
    template_frankfurt = "ydid:crt:65EF4F:329602cf-5945-4aad-a288-ea424d64d55e"

[workerPool]
    templateId = "{{template_{{region}}}}"
```

Then, if one used `yd-provision -v region=phoenix`, the `templateId` property would first resolve to `"{{template_phoenix}}"`, and then to `"ydid:crt:65EF4F:e4239dec-78c2-421c-a7f3-71e61b72946f"`.

There is no limit on how deeply variables can be nested, and a variable whose value itself contains variable references is resolved however long the chain. A circular reference, where a variable refers back to itself either directly or through other variables, is reported as an error. The example is TOML, but `"templateId": "{{template_{{region}}}}"` works the same way in a JSON or Jsonnet specification. Note that sequencing of properties does not matter, e.g. variable `{{a}}` can depend on a variable `{{b}}` that is defined after it in the file.

### Providing Default Values for User-Defined Variables

Each variable can be supplied with a default value, to be used if a value is not explicitly provided for that variable name. The syntax for providing a default is:

```
"{{variable_name:=default_value}}" or
"{{num:numeric_variable_name:=default_numeric_value}}" or
"{{bool:boolean_variable_name:=default_boolean_value}}" or
"{{array:array_name:=default_array}}" or
"{{table:table_name:=default_table}}"
```

An empty-string default variable value can be set as follows: `"{{my_variable:=}}"`.

Examples of use in a TOML file:

```toml
name = "{{name:=my_name}}"
taskCount = "{{num:task_count:=5}}"
finishIfAllTasksFinished = "{{bool:fiaft:=true}}"
arguments = "{{array:args:=[1,2,3]}}"
environment = '{{table:env:={"A":100,"B":200}}}'
```

When a JSON default contains double-quoted strings, use a TOML single-quoted (literal) string to avoid escaping:

```toml
workerTags = '{{array:worker_tags:=["tag1", "tag2"]}}'
```

A default can contain braces of its own, as long as they balance, as a table's JSON or a shell's `${HOME}` does: the substitution ends at the `}}` that follows them.

Default values can be used anywhere that variable substitutions are allowed, and nested variable substitutions can be used inside default values, e.g.:

```toml
name = "{{name_var:={{tag}}-{{datetime}}}}"
```

### Removing Properties Using the Unset Suffix

The `::` suffix can be used to make a property **conditional on a variable being defined**. If the variable is defined, its value is used normally. If the variable is not defined, the property is **removed entirely** from the specification before it is submitted.

The syntax is:

```
"{{variable_name::}}"
```

For example, in a TOML file:

```toml
[workRequirement]
name          = "my-job"
tag           = "{{wr_tag::}}"       # removed if 'wr_tag' is not set
taskCount     = "{{num:tasks::}}"    # removed if 'tasks' is not set
```

If `wr_tag` is not supplied, the `tag` property will be absent from the submitted Work Requirement (rather than being set to an empty string or causing an error). If `wr_tag` is supplied, e.g. via `-v wr_tag=my-tag`, it will be used as the value.

This also works inside JSON/Jsonnet specifications and for list elements. In the contents of files that are substituted as text — User Data files, Task Data files (`taskDataFile`/`taskDataFiles`) and `writeFile` content files — there is no property to remove, so an unset substitution for an undefined variable is left in the text exactly as written.

The `env:` prefix can be combined with the unset suffix to make a property conditional on an environment variable being set:

```toml
region = "{{env:MY_REGION::}}"   # removed if MY_REGION is not set
```

The bare `{{::}}` (no variable name) always removes the property unconditionally — useful for explicitly suppressing a property that a base template includes:

```toml
taskType = "{{::}}"   # always removed
```

An unset expression does not have to be the whole value. Wherever it appears in a string, it removes the **entire** property, list element or variable containing it, not just the expression itself; the rest of the string is discarded with it:

```toml
imageId   = "ami-{{region::}}-base"          # removed entirely if 'region' is not set
arguments = ["--user", "{{user::}}", "--zone={{region::}}a"]  # each element removed separately
site      = "{{app}}-{{zone}} {{::}}"        # always removed, whatever 'app' and 'zone' are
```

The unset suffix can also be used inside a [nested variable](#nested-variables). The property is removed if the unset variable's value is needed, and kept if it is not:

```toml
templateId = "{{template_{{region::}}}}"      # removed if 'region' is not set
name       = "{{name:={{default_name::}}}}"   # removed only if neither 'name' nor 'default_name' is set
```

The nested form is the only way to combine a default with the unset suffix: written in one expression, as in `{{name:=x::}}`, they are an error, since a property with a default value is never removed.

A variable defined with the unset syntax, in `[common.variables]` or elsewhere, is itself removed: `region = "{{::}}"`, or `region = "{{env:MY_REGION::}}"` with `MY_REGION` not set, leaves `region` undefined. A plain reference to it, `{{region}}`, is then treated like a reference to any undefined variable: it is left unsubstituted, with a [warning](#undefined-variables), and the property or variable containing it is kept. To make a property or variable conditional on it too, use the suffix there as well: `zone = "{{region::}}a"` is removed along with `region`.

### Undefined Variables

A variable substitution for a variable that is not defined, and that has neither a default value nor the unset suffix, is left in the specification unchanged, and a warning is printed naming it and the properties it appears in, e.g.:

```
WARNING : Variable '{{regoin}}' is not defined, and has been left unsubstituted in 'taskGroups[0].tasks[0].arguments[1]'
```

Where the variable was defined but has been removed by the [unset syntax](#removing-properties-using-the-unset-suffix), the warning says so, and why:

```
WARNING : Variable '{{site}}' is unset, and has been left unsubstituted in 'name': 'site' is '{{::}}', which always unsets it
```

This applies wherever variables are substituted: specifications and the TOML configuration file, including the `namespace`, `tag` and `url` properties and the `[dataClient]` section and its profiles; the contents of User Data files, Task Data files (`taskDataFile`/`taskDataFiles`) and `yd-nodeaction` `writeFile` content files, where the warning names the file; and the paths given to the data client commands.

Each undefined variable is reported once, however many properties or Tasks it appears in, except in files substituted as text — User Data files, `writeFile` content files and Task Data files — where it is reported once for each file it appears in, so that every file in a `userDataFiles`, `contentFiles` or `taskDataFiles` list that needs correcting is named. The Task and Task Group variables that `yd-submit` defines as it generates each Task (`{{task_name}}`, `{{task_number}}` and the others described under [Task and Task Group Name Substitutions](work-requirements.md#task-and-task-group-name-substitutions)) are never reported. Nor is text that only resembles a variable substitution because its name breaks the [naming rule](#variable-naming), such as `docker ps --format '{{.ID}}'`, which is not a substitution at all; and in Worker Pool and Compute Requirement specifications and User Data only the `__{{variable}}__` form is checked, so Mustache directives for the platform are not reported either. The warnings are suppressed by `--quiet`.

A **circular** variable reference, where a variable's value refers back to the variable itself either directly or through other variables, is an error.

## Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data

In JSON/Jsonnet specifications for Worker Pools and Compute Requirements, variable substitutions **must be prefixed and postfixed by double underscores** `__`, e.g. `__{{username}}__`. This is to disambiguate client-side variable substitutions from server-side Mustache variable processing.

Variable substitutions can also be used within **User Data** to be supplied to instances, for which the same prefix/postfix requirement applies, **including** for User Data supplied directly using the `userData` property in the `workerPool` section of the TOML file.

The same prefix/postfix requirement applies to the content of files referenced by the `contentFile` and `contentFiles` properties in `writeFile` Node Actions — see [Node Actions](worker-pools.md#node-actions).
