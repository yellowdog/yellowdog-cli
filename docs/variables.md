# Variable Substitutions

<!--ts-->
   * [Substituting Numbers, Booleans, Arrays and Tables](#substituting-numbers-booleans-arrays-and-tables)
      * [Details](#details)
   * [Default Variables](#default-variables)
      * [Details](#details-1)
   * [User-Defined Variables](#user-defined-variables)
      * [Variable Naming](#variable-naming)
         * [Details](#details-2)
      * [Setting Variable Values](#setting-variable-values)
      * [Precedence Order](#precedence-order)
         * [Details](#details-3)
      * [Nested Variables](#nested-variables)
      * [Providing Default Values for User-Defined Variables](#providing-default-values-for-user-defined-variables)
         * [Details](#details-4)
      * [Removing Properties Using the Unset Suffix](#removing-properties-using-the-unset-suffix)
         * [Unset Properties and Property Inheritance](#unset-properties-and-property-inheritance)
         * [Details](#details-5)
      * [Undefined Variables](#undefined-variables)
         * [Details](#details-6)
      * [Writing a Substitution Literally](#writing-a-substitution-literally)
         * [Details](#details-7)
   * [Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data](#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data)
      * [Details](#details-8)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:12:23 GMT 2026 -->

<!--te-->


Variable substitutions put values into the configuration file and the specifications when a command runs. Write `{{name}}` in a property's value, and the command replaces it with the value of the variable `name`. For example, with this `config.toml`:

```toml
[common]
    namespace = "image-processing"
    tag = "render"

[common.variables]
    project_code = "pr-213a"

[workRequirement]
    name = "{{project_code}}-{{datetime}}"
    taskType = "bash"
```

and this Work Requirement specification, `render.json`:

```json
{
  "taskGroups": [
    {
      "name": "frames",
      "taskCount": 2,
      "tasks": [
        {"arguments": ["-c", "echo rendering {{project_code}} frame {{task_number}}"]}
      ]
    }
  ]
}
```

`yd workrequirement submit --dry-run render.json` shows a Work Requirement named like `pr-213a-261027-160616`, whose first Task has the arguments `["-c", "echo rendering pr-213a frame 1"]`. To use another value for one run, set it on the command line: `yd workrequirement submit --dry-run -v project_code=pr-300b render.json`. `yd variables` lists every variable and its value.

Substitutions can be used in the value of any property in the TOML configuration file and in JSON and Jsonnet specifications, including values inside arrays (lists), such as `arguments`, and tables (dictionaries), such as `environment`. Write no spaces between the braces and the variable's name: `{{ project_code }}` is not a substitution.

In a JSON file, a substitution is always written inside a string, even for a number, table or array: `"{{num:count}}"`, not `{{num:count}}`. It cannot be used in a property name. The value it gives is substituted as it is, so a Windows path or a quotation mark needs no escaping. A Jsonnet file is more flexible: see [Variable Substitutions in Jsonnet Files](jsonnet.md#variable-substitutions-in-jsonnet-files).

## Substituting Numbers, Booleans, Arrays and Tables

A substitution gives a string. To give a number, a boolean, an array or a table instead, put a type tag before the variable's name: `num:`, `bool:`, `array:` or `table:`. For example, in a Work Requirement specification:

```json
{
  "taskGroups": [
    {
      "maximumTaskRetries": "{{num:retries}}",
      "finishIfAnyTaskFailed": "{{bool:stop_on_failure}}",
      "workerTags": "{{array:worker_tags}}",
      "tasks": [
        {
          "arguments": ["-c", "render.sh --retries={{num:retries}}"],
          "environment": "{{table:task_env}}"
        }
      ]
    }
  ]
}
```

```shell
yd workrequirement submit --dry-run render.json -v retries=2 -v stop_on_failure=true \
    -v 'worker_tags=["gpu", "linux"]' -v 'task_env={"THREADS": "4"}'
```

The values are converted from strings to their JSON types, so the Task Group gets `"maximumTaskRetries": 2`, `"finishIfAnyTaskFailed": true` and `"workerTags": ["gpu", "linux"]`, and the Task `"environment": {"THREADS": "4"}`.

A type-tagged substitution that is only part of a string, such as `"render.sh --retries={{num:retries}}"`, is checked as its type and then written into the string as text: `render.sh --retries=2`.

### Details

**Array and table values.** `array:` and `table:` values are JSON, with double-quoted strings and `true`/`false`/`null`. They can also be written in Python's spelling, with single-quoted strings and `True`/`False`/`None`, which can be easier to quote on a command line: `-v "tags=['a','b']"` rather than `-v 'tags=["a","b"]'`, and on Windows rather than `-v "tags=[\"a\",\"b\"]"`. Python's spelling is read only where the value is not JSON, and only for what JSON could hold: a table's keys must be strings, and a tuple, a set, bytes or a complex number is refused. In a TOML single-quoted (literal) string, which cannot contain a single quote, use JSON.

**Number and boolean values.** A `num:` value may be written in JSON's syntax or Python's, e.g. `5`, `-2.5`, `1e3`, `1E3` or `1_000`. It must be a finite number: `nan` and `inf` are refused, as they are inside an `array:` or `table:`, since JSON cannot carry them. A `bool:` value is `true` or `false` in any case, so `True` and `TRUE` are accepted too.

**A value of the wrong type** is an error naming the substitution, e.g. `Cannot substitute '{{num:count}}': 'abc' is not a number`.

**Part of a string.** A number is written as it was written (`1.10` stays `1.10`). A boolean, array or table is written as JSON (`true`, `["a", "b"]`).

**Files substituted as text.** The same rules hold in User Data scripts, Task Data files and `writeFile` content files. There, `N={{num:count}}` in a shell script becomes `N=5`. A typed substitution standing alone in quotes, `"{{num:count}}"`, loses its quotes, so in a JSON file it becomes the number itself.

**How values are held.** Every variable value is held internally as a string, whatever form it was defined in. A variable defined as something other than a string (an array, table, number or boolean, in `[common.variables]` or with `--property common.variables.<name>=<value>`) is held as its **JSON** text, so that the type tags can read it back. So `counts = [1, 2, 3]` and `counts = "[1,2,3]"` are equivalent definitions, as are `enabled = true` and `enabled = "true"`, and `enabled = true` substitutes as `true` rather than as Python's `True`. TOML's date, time and datetime values have no JSON form, and are held as the text they were written as. `yd variables` reports the stored string, so an array is reported as `"[1, 2, 3]"` rather than as a JSON array.

## Default Variables

The following substitutions are automatically created and can be used in any section of the configuration file, or in any JSON specification:

| Directive             | Description                                                    | Example of Substitution |
|:----------------------|:---------------------------------------------------------------|:------------------------|
| `{{username}}`        | The current user's login username, lower case, spaces replaced | jane_smith              |
| `{{date}}`            | The current date (UTC): YYMMDD                                 | 221027                  |
| `{{time}}`            | The current time (UTC): HHMMSSss                               | 16302699                |
| `{{datetime}}`        | The date and the time to the second (UTC): YYMMDD-HHMMSS       | 221027-163026           |
| `{{random}}`          | Three random base 36 digits (0-9, a-z), lower case             | a1c                     |
| `{{random6}}`         | Six random base 36 digits (0-9, a-z), lower case               | a1c9z0                  |
| `{{pid}}`             | The process ID (PID) of the running command                    | 48213                   |
| `{{pid2}}`            | The process discriminator: the PID mod 1296, in two base 36 digits, lower case | 4f      |
| `{{namespace}}`       | The `namespace` property.                                      | image-processing        |
| `{{tag}}`             | The `tag` property.                                            | render                  |
| `{{key}}`             | The application `key` property.                                |                         |
| `{{secret}}`          | The application `secret` property.                             |                         |
| `{{url}}`             | The Platform `url` property.                                   |                         |
| `{{config_dir_abs}}`  | The absolute directory path of the configuration file          | /yellowdog/workloads    |
| `{{config_dir_name}}` | The immediate containing directory of the configuration file   | workloads               |
| `{{dataClient.remote}}`, `{{dataClient.bucket}}`, `{{dataClient.prefix}}` | The data client's configuration, and `{{dataClient.<profile>.remote}}` and the others a named profile's; see [Variable Substitutions for Data Client Properties](data-client.md#variable-substitutions-for-data-client-properties) | |

A value stays the same for the whole command: if `{{time}}` is used in several properties, each gets the identical value. This holds for `date`, `time`, `datetime`, `random`, `random6`, `pid` and `pid2`.

The `namespace`, `tag`, `key`, `secret` and `url` variables always hold the values the command is using. They cannot be redefined or unset as user-defined variables (see [Variable Naming](#variable-naming)). The other default variables can be overridden, as described in [Precedence Order](#precedence-order).

### Details

**The configuration directory.** The `config_dir_` substitutions use the directory containing the nominated TOML configuration file, or the invocation directory if no configuration file is supplied. With `--no-config`, they are not defined.

**Random values.** The `random` and `random6` directives use base 36 digits rather than hexadecimal. Base 36 is the widest alphabet a YellowDog name may be built from, so they carry the most randomness in the fewest characters: `random` has 46,656 possible values and `random6` has 2,176,782,336.

**The process discriminator.** The `pid2` directive is the same two characters that an automatically generated name ends with (see [Naming Rules](configuration.md#naming-rules)). A hand-written name such as `name = "{{tag}}-{{datetime}}-{{pid2}}"` is therefore disambiguated between simultaneously launched commands exactly as a generated one is. Processes alive at the same time always have distinct PIDs, so `{{pid2}}` differs between them unless 1,296 processes were spawned in between. The `pid` directive is the full PID, which is unambiguous but too long, and too variable in length, to sit comfortably in a name.

## User-Defined Variables

You can define variables of your own on the command line, in environment variables prefixed with `YD_VAR_`, or in the `[common.variables]` section of the TOML configuration file. General environment variables can be read too. [Setting Variable Values](#setting-variable-values) shows each.

### Variable Naming

A variable name starts with a letter, a digit or an underscore, and contains only letters, digits, underscores (`_`), full stops (`.`) and hyphens (`-`): for example `project_code`, `run-2`, `9lives` or `dataClient.prod.bucket`. Names are case-sensitive. A name that breaks this rule is an error wherever the variable is defined, and the error names the definition.

The names `namespace`, `tag`, `key`, `secret` and `url` are reserved for the [default variables](#default-variables) that the CLI defines from its configuration. Set these values with the `[common]` properties, the `YD_NAMESPACE`, `YD_TAG`, `YD_KEY`, `YD_SECRET` and `YD_URL` environment variables, or the `--namespace`/`-n`, `--tag`/`-t`, `--key`, `--secret` and `--url` options instead, as described in [Specifying Common Properties using the Command Line or Environment Variables](configuration.md#specifying-common-properties-using-the-command-line-or-environment-variables).

#### Details

**Where the rule applies.** A name is checked wherever a variable is defined: on the command line, in a `YD_VAR_` environment variable, in `[common.variables]`, and with `--property common.variables.<name>`.

**Reserved names.** Defining a variable with a reserved name is an error at any of those sources. Such a variable would change only what `{{tag}}` (for example) substitutes, not the tag the command actually uses to name and select entities. And one unset with `{{::}}` would simply be defined again from the configuration. Names differing only in case, such as `TAG`, are not reserved.

**Text that is not a substitution.** The same rule decides what a substitution refers to. A `{{...}}` expression whose name breaks it is not a variable substitution at all, and is left as it is. This is what lets text meant for other tools, such as Docker's `{{.ID}}` or a Go template's `{{- .Values.image }}`, pass through unchanged. It is also why a name may not start with `.` or `-`, and why there should be no spaces between a variable name and the curly brackets.

**Syntax that cannot appear in a name.** The rule excludes the substitution syntax itself (`}}`, the `:=` default-value separator and the `::` unset suffix). The type-tag prefixes (`num:`, `bool:`, `array:`, `table:`, `format_name:`) and `env:` have special meaning at the start of a substitution. The exception is the name of a general environment variable in an `{{env:NAME}}` substitution, which is the operating system's to decide: it may contain anything but whitespace and the substitution syntax, e.g. `{{env:ProgramFiles(x86)}}`.

**The case of `YD_VAR_` names.** A `YD_VAR_` environment variable creates a variable name with the **exact case** of the suffix: `YD_VAR_SUFFIX` creates `SUFFIX`, not `suffix`. On Windows, environment variable names are uppercased by the OS, so use uppercase names only.

### Setting Variable Values

1. **On the command line**, with `--variable` or `-v`: `yd workrequirement submit -v project_code=pr-213a -v run_id=1234` defines `{{project_code}}` and `{{run_id}}`, substituted by `pr-213a` and `1234`.
2. **In a `YD_VAR_` environment variable**: `YD_VAR_project_code="pr-213a"` defines `{{project_code}}`, substituted by `pr-213a`. On Windows, environment variable names are case-insensitive and converted to upper case, so choose upper-case variable names only.
3. **In any other environment variable**, read with the `env:` prefix: `{{env:RENDER_QUALITY}}`. A type tag goes before the prefix, as in `{{num:env:THREADS}}`. A default, used when the environment variable is not set, goes after the name: `{{env:RENDER_QUALITY:=high}}`.
4. **In the TOML configuration file**, in a `variables` table in the `[common]` section, e.g. `variables = {project_code = "pr-213a", run_id = "1234"}`, or in this form:

```toml
[common.variables]
    project_code = "pr-213a"
    run_id = "1234"
```

A TOML value that is not a string is converted to its JSON text when it is loaded. So `counts = [1, 2, 3]` can be used as `"{{array:counts}}"` exactly as `counts = "[1,2,3]"` can, and `enabled = true` substitutes as `true` (see **How values are held** under [Substituting Numbers, Booleans, Arrays and Tables](#substituting-numbers-booleans-arrays-and-tables)).

### Precedence Order

When a variable is set in more than one place, the first of these wins:

1. The command line: `--variable`/`-v`, or `--property common.variables.<name>=<value>`
2. `YD_VAR_` environment variables
3. `YD_VAR_` variables defined in a `.env` file
4. The TOML configuration file (`[common.variables]`)
5. The [default variables](#default-variables) (`username`, `date`, `random` and the others, other than the reserved `namespace`, `tag`, `key`, `secret` and `url`)

So a variable of your own overrides a default variable of the same name: `-v username=render-bot` replaces the default `{{username}}`.

#### Details

**A configuration file chosen with `--config`.** If the configuration file is explicitly selected using the `--config`/`-c` option, its `[common.variables]` definitions take precedence over `YD_VAR_` environment variables (items 2 and 3). They never take precedence over variables set on the command line.

**`--env-override`.** With `--env-override` (or `YD_ENV_OVERRIDE` set), a `.env` file's `YD_VAR_` variables take precedence over the environment's: items 2 and 3 change places. [Which Value Wins](configuration.md#which-value-wins) sets this order beside those of the other kinds of setting.

**`--property common.variables.<name>`** is the same as `-v`. It is in place before the configuration file is read, so the file's own values and the variables built from it take it too.

**`{{env:NAME}}` substitutions** are resolved directly from the named environment variable at the point of use, and do not take part in this precedence order.

### Nested Variables

Variable substitutions can be nested, in TOML, JSON and Jsonnet files alike. For example, to select a different `templateId` for a Worker Pool depending on the value of a `region` variable:

```toml
[common.variables]
    template_london = "ydid:crt:65EF4F:a4d757cf-b67a-4eb6-bd39-8a6ffd46c8f4"
    template_phoenix = "ydid:crt:65EF4F:e4239dec-78c2-421c-a7f3-71e61b72946f"
    template_frankfurt = "ydid:crt:65EF4F:329602cf-5945-4aad-a288-ea424d64d55e"

[workerPool]
    templateId = "{{template_{{region}}}}"
```

With `yd workerpool provision -v region=phoenix`, the `templateId` property first resolves to `"{{template_phoenix}}"`, and then to `"ydid:crt:65EF4F:e4239dec-78c2-421c-a7f3-71e61b72946f"`. The example is TOML, but `"templateId": "{{template_{{region}}}}"` works the same way in a JSON or Jsonnet specification.

There is no limit on how deeply variables can be nested, and a variable whose value itself contains variable references is resolved however long the chain. The order of definitions does not matter: a variable `{{a}}` can depend on a variable `{{b}}` defined after it in the file. A circular reference, where a variable refers back to itself either directly or through other variables, is reported as an error.

### Providing Default Values for User-Defined Variables

A default value is used when no value is provided for the variable. Write it after the name, following `:=`: `"{{run_name:=nightly-render}}"`. A type-tagged substitution takes a default of its type. In a TOML file:

```toml
[workRequirement]
    name = "{{run_name:=nightly-render}}"
    taskCount = "{{num:task_count:=5}}"
    finishIfAllTasksFinished = "{{bool:finish_when_done:=true}}"
    arguments = '{{array:args:=["-c", "render.sh --quality high"]}}'
    environment = '{{table:task_env:={"THREADS": "4", "LOG_LEVEL": "info"}}}'
```

When a default contains double-quoted strings, as a JSON array or table does, write the property as a TOML single-quoted (literal) string, as above, to avoid escaping them.

An empty default is written with nothing after the `:=`: `"{{name_suffix:=}}"`.

Defaults can be used anywhere that variable substitutions are allowed, and can contain nested variable substitutions:

```toml
name = "{{run_name:={{tag}}-{{datetime}}}}"
```

#### Details

**Braces in a default.** A default can contain braces of its own, as long as they balance, as a table's JSON or a shell's `${HOME}` does: the substitution ends at the `}}` that follows them.

### Removing Properties Using the Unset Suffix

The `::` suffix makes a property **conditional on a variable being defined**. If the variable is defined, its value is used normally. If it is not, the property is **removed entirely** from the specification before it is submitted:

```toml
[workRequirement]
    name       = "nightly-render"
    workerTags = "{{array:worker_tags::}}"   # removed if 'worker_tags' is not set
    taskCount  = "{{num:tasks::}}"           # removed if 'tasks' is not set
```

If `worker_tags` is not supplied, the `workerTags` property is absent from the submitted Work Requirement, rather than being set to an empty value or causing an error. If it is supplied, e.g. with `-v "worker_tags=['gpu']"`, its value is used. This works the same way in JSON and Jsonnet specifications, and for list elements.

The `env:` prefix can be combined with the unset suffix to make a property conditional on an environment variable being set:

```toml
region = "{{env:RENDER_REGION::}}"   # removed if RENDER_REGION is not set
```

The bare `{{::}}`, with no variable name, always removes the property. This is useful for suppressing a property that a base template includes:

```toml
taskType = "{{::}}"   # always removed
```

In a Work Requirement, a removed property is still inherited from the level above: see [Unset Properties and Property Inheritance](#unset-properties-and-property-inheritance).

An unset expression does not have to be the whole value. Wherever it appears in a string, it removes the **entire** property, list element or variable containing it, not just the expression itself. The rest of the string is discarded with it:

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

#### Unset Properties and Property Inheritance

In a Work Requirement, removing a property is not the same as clearing it. A property removed by the unset syntax is treated exactly as if it had never been written at that level, so it is still [inherited](work-requirements.md#property-inheritance) from the level above: from the Task Group, the Work Requirement or the `[workRequirement]` section of the TOML file, whichever is the nearest to set it. `{{::}}` therefore cannot be used to stop a Task Group or a Task receiving a value set higher up. To do that, set the property to `null` at that level, as described in [Stopping Inheritance with `null`](work-requirements.md#stopping-inheritance-with-null).

For example, with `arguments = ["--verbose"]` in the `[workRequirement]` section of the TOML file:

```json
{
  "taskGroups": [
    {"name": "tg-1", "arguments": "{{::}}", "tasks": [{"name": "task-1"}]},
    {"name": "tg-2", "arguments": null, "tasks": [{"name": "task-2"}]},
    {"name": "tg-3", "arguments": ["{{::}}"], "tasks": [{"name": "task-3"}]},
    {"name": "tg-4", "tasks": [{"name": "task-4", "arguments": ["x"]}]}
  ]
}
```

- `task-1` runs with `["--verbose"]`: `tg-1`'s `arguments` is removed, so `tg-1` inherits it from the TOML file and passes it on.
- `task-2` runs with no arguments: `null` stops the inheritance.
- `task-3` runs with no arguments too: the `{{::}}` is a list element, so only that element is removed, leaving `tg-3` with an empty list of its own, which stops the inheritance as `null` does.
- `task-4` runs with `["x"]`, its own setting, which takes precedence over the inherited one.

The same holds when the unset is conditional: `"arguments": "{{extra_args::}}"` on a Task Group uses `extra_args` if it is defined, and otherwise lets the Task Group inherit `arguments` from above as if the line were not there. To have no arguments instead when `extra_args` is undefined, give it an empty default with a type tag, which stops the inheritance as `null` would: `"arguments": "{{array:extra_args:=[]}}"`.

#### Details

**Files substituted as text.** In the contents of User Data files, Task Data files (`taskDataFile`/`taskDataFiles`) and `writeFile` content files there is no property to remove. An unset substitution for an undefined variable is left in the text exactly as written.

**A default and the unset suffix together.** The nested form above is the only way to combine them. Written in one expression, as in `{{name:=x::}}`, they are an error, since a property with a default value is never removed.

**A variable defined as unset.** A variable defined with the unset syntax, in `[common.variables]` or elsewhere, is itself removed: `region = "{{::}}"`, or `region = "{{env:RENDER_REGION::}}"` with `RENDER_REGION` not set, leaves `region` undefined. A plain reference to it, `{{region}}`, is then treated like a reference to any undefined variable: it is left unsubstituted, with a [warning](#undefined-variables), and the property or variable containing it is kept. To make a property or variable conditional on it too, use the suffix there as well: `zone = "{{region::}}a"` is removed along with `region`.

### Undefined Variables

A substitution for a variable that is not defined, and that has neither a default value nor the unset suffix, is left in the specification unchanged. A warning names it and the properties it appears in:

```
WARNING : Variable '{{regoin}}' is not defined, and has been left unsubstituted in 'taskGroups[0].tasks[0].arguments[1]'
```

Where the variable was defined but has been removed by the [unset syntax](#removing-properties-using-the-unset-suffix), the warning says so, and why:

```
WARNING : Variable '{{site}}' is unset, and has been left unsubstituted in 'name': 'site' is '{{::}}', which always unsets it
```

A substitution has no space inside its braces: `{{ region }}` is not a substitution, and is left as it is, so that templates for other tools (`{{ .Values.x }}`, Jinja2's `{{ name }}`) pass through. Where the name inside is one that would be substituted without the space, a warning says so, once:

```
WARNING : '{{ region }}' has space inside its braces, so it is not a variable substitution, and has been left unchanged in 'taskGroups[0].tasks[0].arguments[1]'; write '{{region}}' to substitute it
```

To pass `{{region}}` itself through, unsubstituted, write it as described under [Writing a Substitution Literally](#writing-a-substitution-literally).

A **circular** variable reference, where a variable's value refers back to the variable itself either directly or through other variables, is an error.

The warnings are suppressed by `--quiet`.

#### Details

**Where the warnings apply.** Wherever variables are substituted: specifications and the TOML configuration file, including the `namespace`, `tag` and `url` properties and the `[dataClient]` section and its profiles; the contents of User Data files, Task Data files (`taskDataFile`/`taskDataFiles`) and `yd node action` `writeFile` content files, where the warning names the file; and the paths given to the data client commands.

**How often.** Each undefined variable is reported once, however many properties or Tasks it appears in. The exception is the files substituted as text (User Data files, `writeFile` content files and Task Data files), where it is reported once for each file it appears in, so that every file in a `userDataFiles`, `contentFiles` or `taskDataFiles` list that needs correcting is named.

**What is never reported.** The Task and Task Group variables that `yd workrequirement submit` defines as it generates each Task (`{{task_name}}`, `{{task_number}}` and the others described under [Task and Task Group Name Substitutions](work-requirements.md#task-and-task-group-name-substitutions)). Text that only resembles a variable substitution because its name breaks the [naming rule](#variable-naming), such as `docker ps --format '{{.ID}}'`, which is not a substitution at all. And in Worker Pool and Compute Requirement specifications and User Data only the `__{{variable}}__` form is checked, so Mustache directives for the platform are not reported either.

**A space inside the braces** is warned of only where the name is one that would be substituted without the space: a variable that is defined, an environment variable that is set, or one of the Task variables.

### Writing a Substitution Literally

To have the text `{{name}}` itself, unsubstituted, write `raw:` after the opening braces: `{{raw:name}}` becomes `{{name}}`, which is substituted no further, whatever `name` is. You need this when text meant for another tool, such as a template for a program a Task runs, contains `{{name}}` where `name` is also a variable here, one of the [default variables](#default-variables) such as `{{date}}` or `{{username}}`, or one of the Task variables such as `{{task_name}}`.

| Written | Becomes |
|---|---|
| `{{raw:date}}` | `{{date}}` |
| `"--template={{raw:task_number}}-{{task_number}}"` | `"--template={{task_number}}-1"` |
| `{{raw:num:count}}` | `{{num:count}}` |
| `{{raw:region:=eu}}` | `{{region:=eu}}` |
| `{{raw:prefix_{{site}}}}` | `{{prefix_{{site}}}}` |

#### Details

**Everything after `raw:` is text**, as written: a type tag, a default, the unset suffix and a substitution nested inside it are not acted on.

**A type tag cannot come before `raw:`**, since the text has no type: `{{num:raw:count}}` is an error, saying to write `{{raw:num:count}}`.

**As a default or a variable's value.** A `raw:` substitution can be a default: `{{region:={{raw:region}}}}` gives `{{region}}` where `region` is undefined. A variable can hold one: with `-v template={{raw:date}}`, `{{template}}` becomes `{{date}}`.

**Where it works.** Wherever substitutions do: in the `__{{raw:name}}__` form in Worker Pool and Compute Requirement specifications and User Data (becoming `__{{name}}__`), in a CSV file's cells, and in the files substituted as text. In a Jsonnet file it is written inside a string.

## Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data

The Platform runs Mustache templates of its own in User Data and Node Actions. There, write a substitution of yours with a double underscore before and after it, `__{{username}}__`; a plain `{{...}}` is left for the Platform, unsubstituted and unreported. For example:

```toml
[common.variables]
    site = "london"

[workerPool]
    templateId = "ydid:crt:65EF4F:a4d757cf-b67a-4eb6-bd39-8a6ffd46c8f4"
    workerTag = "{{site}}"
    userData = "#!/bin/bash\necho 'Provisioned by __{{username}}__ for __{{site}}__ on {{provider}}' > /var/log/provisioned.txt"
```

`yd workerpool provision --dry-run` shows the `workerTag` as `london`, and the User Data as `echo 'Provisioned by jane_smith for london on {{provider}}'`, leaving `{{provider}}` for the Platform to fill in on each instance.

User Data templates can use the instance's details (`{{provider}}`, `{{region}}`, `{{#imageOs:linux}}`...). Node Actions' `writeFile` and `runCommand` actions can use the Nodes' (`{{node.details.hostname}}`, `{{nodesByType.type1}}`...). Everywhere else the plain form is used, and Worker Pool and Compute Requirement specifications take either:

| Where | Form |
|---|---|
| User Data, wherever it is given: a `userData` property (in the `[workerPool]` or `[computeRequirement]` section of the configuration file, or in any specification, a Compute Requirement Template resource's included), and the files named by `userDataFile` and `userDataFiles` | `__{{variable}}__` |
| `yd node action` specification files, every property, and the files named by a `writeFile` action's `contentFile` and `contentFiles` | `__{{variable}}__` |
| Node Actions in a Worker Pool specification or a Configured Worker Pool resource (`nodeEvents`, everything in it) | `__{{variable}}__` |
| Every other property of a Worker Pool or Compute Requirement specification file (JSON or Jsonnet) | `__{{variable}}__` or `{{variable}}` |
| Work Requirement specifications, resource specifications (bar their User Data and Node Actions), Task Data files, and the rest of the configuration file, `[workerPool]` and `[computeRequirement]` included | `{{variable}}` |
| A CSV file's values in a prototype Task | `<<column>>` (see [CSV Variable Substitutions](work-requirements.md#csv-variable-substitutions)) |

So a Worker Pool's `workerTag` can be `"{{site}}"` in `[workerPool]` and in a Worker Pool specification alike.

Everything else about a substitution — [type tags](#substituting-numbers-booleans-arrays-and-tables), [defaults](#providing-default-values-for-user-defined-variables), the [unset suffix](#removing-properties-using-the-unset-suffix), nesting, [writing one literally](#writing-a-substitution-literally) — is the same in both forms, inside the underscores: `__{{num:count:=1}}__`, and `__{{raw:name}}__` for the text `__{{name}}__`.

### Details

**Order.** In a Worker Pool or Compute Requirement specification, the `__{{variable}}__` form is substituted first, then the plain one.

**Jsonnet files.** A Jsonnet file is substituted twice: once before it is evaluated, as text, and once after, property by property. The first is what the Jsonnet code itself works with — `std.parseInt("{{count}}")`, a comparison, a computed field name. It is made in the file's own form only, since the text says nothing of which property it is in: `__{{variable}}__` in a Worker Pool or Compute Requirement specification, and the plain `{{variable}}` in any other file, where a `__{{variable}}__` is left for the second. The second makes the rest, as the table says. See also [Variable Substitutions in Jsonnet Files](jsonnet.md#variable-substitutions-in-jsonnet-files).

**Plain substitutions in a Worker Pool or Compute Requirement Jsonnet file** come out substituted in a string, but the code cannot compute with them.

**A Platform template in a Jsonnet resource file.** In a Jsonnet resource file, a plain `{{variable}}` in its User Data or Node Actions is substituted before evaluation if it is defined. So a Platform template there with the name of a variable of ours, `{{region}}` say, is written `{{raw:region}}` (see [Writing a Substitution Literally](#writing-a-substitution-literally)).
