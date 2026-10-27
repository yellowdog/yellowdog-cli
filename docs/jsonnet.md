# Jsonnet Support

<!--ts-->
   * [Jsonnet Installation](#jsonnet-installation)
   * [Variable Substitutions in Jsonnet Files](#variable-substitutions-in-jsonnet-files)
   * [Checking Jsonnet Processing](#checking-jsonnet-processing)
   * [Jsonnet Example](#jsonnet-example)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 09:11:59 GMT 2026 -->

<!--te-->


In all circumstances where JSON files are used by the YellowDog CLI commands, **[Jsonnet](https://jsonnet.org)** files can be used instead. This allows the use of Jsonnet's powerful JSON extensions, including comments, variables, functions, etc. A variable substitution inside a comment is left as it is, so commenting out a line that holds one comments it out.

A simple usage example might be:

```shell
yd workrequirement submit my_work_req.jsonnet
```

The use of the filename extension `.jsonnet` will activate Jsonnet evaluation. The file is evaluated in memory, after variable substitution. An error message names the `.jsonnet` file itself, and its imports are found beside it, or failing that in the current directory.

## Jsonnet Installation

Jsonnet is **not** installed by default. If you try to use a Jsonnet file without it installed, the commands will print an error with installation instructions.

On most platforms Jsonnet installs as a prebuilt wheel and needs nothing else. There is no wheel for Linux on Arm (`aarch64`), for Intel macOS, for Windows on Arm, or for Linux distributions older than Debian 9 / Ubuntu 17.04; on those, pip compiles Jsonnet from source, which needs a C++ compiler — `build-essential` on Debian/Ubuntu. `yd version` reports whether Jsonnet is installed, and which version.

Install it as an extra, the way the CLI was installed (see [Installation](../README.md#installation)):

**With uv tool:**

```shell
uv tool install "yellowdog-cli[jsonnet]"
```

To update: `uv tool upgrade yellowdog-cli`

**In a virtual environment created with uv**, with the environment activated:

```shell
uv pip install -U "yellowdog-cli[jsonnet]"
```

**With pip in a virtual environment**, with the environment activated:

```shell
pip install -U "yellowdog-cli[jsonnet]"
```

## Variable Substitutions in Jsonnet Files

The commands provide full support for variable substitutions in Jsonnet files. In **Worker Pool** and **Compute Requirement** specifications, a variable substitution the Jsonnet code computes with (`std.parseInt("__{{count}}__")`, a comparison) must be prefixed and postfixed by double underscores (`__`), since the plain form is substituted there only after evaluation; one that is simply part of a string can take either form (see [which form to use](variables.md#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data)).

Variable substitution is performed before Jsonnet expansion into JSON, **and** again after the expansion. Variables are fully resolved before the expansion, including those whose values themselves contain variable references, so Jsonnet code can compute with their values, e.g. `local count = std.parseInt('{{count}}');`.

A Jsonnet file's `import` and `importstr` paths are resolved relative to the file itself, wherever the command is run from, and then, as a fallback, relative to the current directory. An error in the Jsonnet names the file and the line. The file is read as UTF-8.

Because the substitution before the expansion is made in the Jsonnet text itself, a substitution can be placed anywhere in it, unlike in a JSON file:

* **Inside a string**, the value is written with that string's escaping, so a Windows path, a quotation mark or an apostrophe needs none of its own, and a default is read the same way, so `"{{env:={\"A\":1}}}"` has the default `{"A":1}`. This holds for every kind of Jsonnet string: double- and single-quoted, verbatim (`@"..."`, `@'...'`) and text blocks (`|||`), where a value of several lines keeps the block's indentation.
* **Outside a string**, the value is inserted as Jsonnet code: `{{expr}}` with `expr = "1 + 2"` evaluates to `3`, and a typed substitution is inserted as its JSON, so `{{num:count}} + 1` is a number.

## Checking Jsonnet Processing

There are three possibilities for verifying that a Jsonnet specification is doing what is intended:

1. To inspect the basic conversion of Jsonnet into JSON, without any additional processing by the YellowDog CLI commands, the `yd jsonnet2json` command can be used. This takes the name(s) of the Jsonnet file(s) to be processed:

```shell
yd jsonnet2json my_file.jsonnet
```

It makes no variable substitution, so a `{{variable}}` is left as written, and finds an `import` beside the file importing it, not in the current directory as the commands also do. With several files or a glob pattern, it writes each conversion to a `<name>.json` file beside its source, asking before it replaces one that differs (see [yd jsonnet2json](commands.md#yd-jsonnet2json)).


2. The `jsonnet-dry-run` (`-J`) option of the `yd workrequirement submit`, `yd workerpool provision`, `yd computerequirement instantiate`, `yd node action`, `yd resource create` and `yd resource remove` commands will generate JSON output representing the Jsonnet to JSON processing only, including applicable variable substitutions, but before full property expansion into the JSON that will be submitted to the Platform.


3. The `dry-run` (`-D`) option will generate JSON output representing the full processing of the Jsonnet file into what will be submitted to the API. This allows inspection to check that the output matches expectations, prior to submitting to the Platform.

## Jsonnet Example

Here's an example of a Jsonnet file that generates a Work Requirement with four Tasks:

```jsonnet
# Function for synthesising Tasks
local Task(arguments=[], environment={}) = {
    arguments: arguments,
    environment: environment,
    name: "my_task_{{task_number}}"
};

# Work Requirement
{
  "name": "workreq_{{datetime}}",
  "taskGroups": [
    {
      "tasks": [
        Task(["1"], {A: "A_1"}),  # arguments and environment
        Task(["2", "3"], {}),     # arguments and empty environment
        Task(["4"]),              # arguments and default environment
        Task()                    # default arguments and environment
      ]
    }
  ]
}
```

When this is inspected using the `jsonnet-dry-run` option (`yd workrequirement submit -Jq my_work_req.jsonnet`), this is the processed output:

```json
{
  "name": "workreq_230114-140645",
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["1"],
          "environment": {"A": "A_1"},
          "name": "my_task_{{task_number}}"
        },
        {
          "arguments": ["2", "3"],
          "environment": {},
          "name": "my_task_{{task_number}}"
        },
        {
          "arguments": ["4"],
          "environment": {},
          "name": "my_task_{{task_number}}"
        },
        {
          "arguments": [],
          "environment": {},
          "name": "my_task_{{task_number}}"
        }
      ]
    }
  ]
}
```

When this is inspected using the `dry-run` option (`yd workrequirement submit -D my_work_req.jsonnet`), this is the processed output:

```json
{
  "name": "workreq_230114-140645",
  "namespace": "pyexamples",
  "priority": 0,
  "tag": "pyex-docker",
  "taskGroups": [
    {
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "name": "task_group_1",
      "priority": 0,
      "runSpecification": {
        "maximumTaskRetries": 0,
        "taskTypes": ["docker"],
        "workerTags": ["pyex-docker"]
      },
      "tasks": [
        {
          "arguments": ["1"],
          "environment": {"A": "A_1"},
          "name": "my_task_1",
          "taskType": "docker"
        },
        {
          "arguments": ["2", "3"],
          "environment": {},
          "name": "my_task_2",
          "taskType": "docker"
        },
        {
          "arguments": ["4"],
          "environment": {},
          "name": "my_task_3",
          "taskType": "docker"
        },
        {
          "arguments": [],
          "environment": {},
          "name": "my_task_4",
          "taskType": "docker"
        }
      ]
    }
  ]
}
```
