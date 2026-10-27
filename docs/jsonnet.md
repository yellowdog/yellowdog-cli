# Jsonnet Support

<!--ts-->
   * [Jsonnet Installation](#jsonnet-installation)
   * [Variable Substitutions in Jsonnet Files](#variable-substitutions-in-jsonnet-files)
      * [Details](#details)
   * [Checking Jsonnet Processing](#checking-jsonnet-processing)
      * [Details](#details-1)
   * [Jsonnet Example](#jsonnet-example)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:12:22 GMT 2026 -->

<!--te-->




Wherever the YellowDog CLI commands take a JSON file, they also take a **[Jsonnet](https://jsonnet.org)** file. Jsonnet extends JSON with comments, variables, functions and more, so a specification can be generated rather than written out. Give the file the `.jsonnet` extension, and the command evaluates it as Jsonnet:

```shell
yd workrequirement submit render.jsonnet
```

The file is evaluated in memory, after variable substitution.

## Jsonnet Installation

Jsonnet is **not** installed by default. If you try to use a Jsonnet file without it installed, the commands print an error with installation instructions. Install it as an extra, the way the CLI was installed (see [Installation](../README.md#installation)):

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

`yd version` reports whether Jsonnet is installed, and which version.

On most platforms Jsonnet installs as a prebuilt wheel and needs nothing else. There is no wheel for Linux on Arm (`aarch64`), for Intel macOS, for Windows on Arm, or for Linux distributions older than Debian 9 / Ubuntu 17.04. On those, pip compiles Jsonnet from source, which needs a C++ compiler: `build-essential` on Debian/Ubuntu.

## Variable Substitutions in Jsonnet Files

[Variable substitutions](variables.md) work in a Jsonnet file as in a JSON file. They are made before the file is evaluated as well as after, so the Jsonnet code can compute with a variable's value. This Work Requirement has one Task per frame, three unless `frames` is set:

```jsonnet
local frames = std.parseInt("{{frames:=3}}");

{
  name: "render-{{datetime}}",
  taskGroups: [
    {
      tasks: [
        {arguments: ["-c", "render.sh --frame " + f]}
        for f in std.range(1, frames)
      ],
    },
  ],
}
```

`yd workrequirement submit --jsonnet-dry-run -v frames=2 frames.jsonnet` shows the two Tasks it generates.

In **Worker Pool** and **Compute Requirement** specifications, a substitution the Jsonnet code computes with must be written with double underscores before and after it: `std.parseInt("__{{count}}__")`. One that is simply part of a string can take either form (see [which form to use](variables.md#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data)).

### Details

**Why Worker Pool and Compute Requirement specifications differ.** There, the plain `{{variable}}` form is substituted only after evaluation, so the code cannot compute with it. The `__{{variable}}__` form is substituted before.

**Chains are resolved first.** Variables are fully resolved before evaluation, including those whose values themselves contain variable references, so the code works with the final value, e.g. `local count = std.parseInt('{{count}}');`.

**A substitution can be placed anywhere in the text.** The substitution before evaluation is made in the Jsonnet text itself, so, unlike in a JSON file, it is not confined to strings:

* **Inside a string**, the value is written with that string's escaping, so a Windows path, a quotation mark or an apostrophe needs none of its own. A default is read the same way, so `"{{env:={\"A\":1}}}"` has the default `{"A":1}`. This holds for every kind of Jsonnet string: double- and single-quoted, verbatim (`@"..."`, `@'...'`) and text blocks (`|||`), where a value of several lines keeps the block's indentation.
* **Outside a string**, the value is inserted as Jsonnet code: `{{expr}}` with `expr = "1 + 2"` evaluates to `3`. A typed substitution is inserted as its JSON, so `{{num:count}} + 1` is a number.

**Comments.** A variable substitution inside a comment is left as it is, so commenting out a line that holds one comments it out.

**Imports, errors and encoding.** A Jsonnet file's `import` and `importstr` paths are resolved relative to the file itself, wherever the command is run from, and then, as a fallback, relative to the current directory. An error in the Jsonnet names the file and the line. The file is read as UTF-8.

## Checking Jsonnet Processing

There are three ways to check that a Jsonnet specification does what is intended:

1. **`yd jsonnet2json`** shows the basic conversion of Jsonnet into JSON, without any additional processing by the CLI: `yd jsonnet2json render.jsonnet`.
2. **`--jsonnet-dry-run`** (`-J`) shows the JSON the Jsonnet produces, with the variable substitutions applied, but before it is expanded into the full specification that would be submitted to the Platform. The `yd workrequirement submit`, `yd workerpool provision`, `yd computerequirement instantiate`, `yd node action`, `yd resource create` and `yd resource remove` commands take it.
3. **`--dry-run`** (`-D`) shows the full processing of the Jsonnet file into what would be submitted to the API, so that you can check it before submitting to the Platform.

### Details

**`yd jsonnet2json` makes no variable substitution**, so a `{{variable}}` is left as written. It finds an `import` only beside the file importing it, while the other commands also look in the current directory. With several files or a glob pattern, it writes each conversion to a `<name>.json` file beside its source, asking before it replaces one that differs (see [yd jsonnet2json](commands.md#yd-jsonnet2json)).

## Jsonnet Example

Here's an example of a Jsonnet file, `render.jsonnet`, that generates a Work Requirement with four Tasks, using a function with default arguments:

```jsonnet
# Function for synthesising Tasks
local Task(frames="1-10", environment={}) = {
  arguments: ["-c", "render.sh --frames " + frames],
  environment: environment,
  name: "render_{{task_number}}",
};

# Work Requirement
{
  name: "render_{{datetime}}",
  taskGroups: [
    {
      tasks: [
        Task("1-10", {THREADS: "8"}),  # frames and environment
        Task("11-20", {}),             # frames and empty environment
        Task("21-30"),                 # frames and default environment
        Task(),                        # default frames and environment
      ],
    },
  ],
}
```

When this is inspected using the `--jsonnet-dry-run` option (`yd workrequirement submit -Jq render.jsonnet`), this is the processed output:

```json
{
  "name": "render_261027-160753",
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["-c", "render.sh --frames 1-10"],
          "environment": {"THREADS": "8"},
          "name": "render_{{task_number}}"
        },
        {
          "arguments": ["-c", "render.sh --frames 11-20"],
          "environment": {},
          "name": "render_{{task_number}}"
        },
        {
          "arguments": ["-c", "render.sh --frames 21-30"],
          "environment": {},
          "name": "render_{{task_number}}"
        },
        {
          "arguments": ["-c", "render.sh --frames 1-10"],
          "environment": {},
          "name": "render_{{task_number}}"
        }
      ]
    }
  ]
}
```

When it is inspected using the `--dry-run` option (`yd workrequirement submit -Dq render.jsonnet`), with `namespace = "image-processing"`, `tag = "render"` and `taskType = "bash"` in the configuration file, this is the processed output:

```json
{
  "namespace": "image-processing",
  "name": "render_261027-160753",
  "taskGroups": [
    {
      "name": "task_group_1",
      "runSpecification": {
        "taskTypes": ["bash"],
        "maximumTaskRetries": 0
      },
      "priority": 0,
      "starved": false,
      "waitingOnDependency": false,
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "tasks": [
        {
          "name": "render_1",
          "taskType": "bash",
          "arguments": ["-c", "render.sh --frames 1-10"],
          "environment": {"THREADS": "8"}
        },
        {
          "name": "render_2",
          "taskType": "bash",
          "arguments": ["-c", "render.sh --frames 11-20"]
        },
        {
          "name": "render_3",
          "taskType": "bash",
          "arguments": ["-c", "render.sh --frames 21-30"]
        },
        {
          "name": "render_4",
          "taskType": "bash",
          "arguments": ["-c", "render.sh --frames 1-10"]
        }
      ]
    }
  ],
  "tag": "render"
}
```
