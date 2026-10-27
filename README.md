# YellowDog Command-Line Interface

<!--ts-->
* [Overview](#overview)
* [YellowDog Prerequisites](#yellowdog-prerequisites)
* [What It Looks Like](#what-it-looks-like)
* [Installation](#installation)
* [YellowDog Commander (GUI)](#yellowdog-commander-gui)
* [YellowDog MCP Server](#yellowdog-mcp-server)
* [Usage](#usage)
   * [Shell Completion](#shell-completion)
   * [Specification Schemas](#specification-schemas)
   * [Applications That Can Read Only Some Namespaces](#applications-that-can-read-only-some-namespaces)
   * [Machine-readable Output and Exit Codes](#machine-readable-output-and-exit-codes)
* [Typical Workflow](#typical-workflow)
* [Documentation](#documentation)
   * [Guides](#guides)
   * [Reference](#reference)
   * [Optional Extensions](#optional-extensions)
   * [The Project](#the-project)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:18:58 GMT 2026 -->

<!--te-->

# Overview

This repository contains a set of command-line utilities for driving the YellowDog Platform, written in Python. The commands use the **[YellowDog Python SDK](https://docs.yellowdog.ai/sdk/python/index.html)**, the code for which can be found [on GitHub](https://github.com/yellowdog/yellowdog-sdk-python-public).

This documentation should be read in conjunction with the main **[YellowDog Documentation](https://docs.yellowdog.ai)**, which provides a comprehensive description of the concepts and operation of the YellowDog Platform.

The CLI is one command, `yd`. Most of what it does names the object acted on, then what to do to it — `yd workrequirement submit`, `yd instance terminate` — and `yd <noun> --help` lists a noun's verbs; `yd` alone, or `yd help`, lists everything. The commands provide the following capabilities:

- **Work Requirements** — submitting, cancelling, holding, starting, finishing and reprioritising them, and comparing them against Worker Pools, with **`yd workrequirement`** (short form `yd wr`)
- **Task Groups and Tasks** — reprioritising Task Groups and comparing them against Worker Pools with **`yd taskgroup`** (`yd tg`), and aborting running Tasks with **`yd task`**
- **Worker Pools** — provisioning, resizing and shutting them down, and refreshing or regenerating Configured Worker Pools' tokens, with **`yd workerpool`** (`yd wp`)
- **Compute Requirements** — instantiating, resizing, stopping, starting, reprovisioning, terminating and setting when they are automatically terminated with **`yd computerequirement`** (`yd cr`)
- **Instances and Nodes** — stopping, starting, restarting, deprovisioning and terminating individual Instances with **`yd instance`**, and Worker Pool Nodes' Instances with **`yd node`**, which also shuts Nodes down and submits Node Actions to them; listing and showing Workers with **`yd worker`**
- **Resources** — creating, updating and removing Compute Source Templates, Compute Requirement Templates, Keyrings, Credentials, Image Families, Namespaces, Allowances, Configured Worker Pools, Attribute Definitions, Namespace Policies, Groups, Applications and Users (update only) with **`yd resource`**, from specification files or on the command line, and showing or removing them by name
- **Allowances** — boosting them with **`yd allowance`**
- **Remote data stores** — uploading, downloading, listing, deleting and copying files with **`yd data`**
- **Cloud regions, instance types and prices**, as the YellowDog Platform knows them, with **`yd cloudinfo`**
- **Inspecting** — listing items with **`yd list`**, showing one in full with **`yd show`**, following event streams with **`yd follow`**, and waiting for Work Requirements, Worker Pools or Compute Requirements to finish with **`yd wait`**. Each Platform noun has `list` and `show` verbs of its own, such as `yd task list --within my-work-requirement --status failed`.
- **Showing** the details of the current Application with the **`yd application`** command
- **Diagnosing** the configuration, credentials and connectivity with the **`yd doctor`** command
- **Reporting** the processed values of variable substitutions with the **`yd variables`** command
- **Completing** commands, verbs, options and their values on Tab, in bash, zsh, fish and PowerShell, with the **`yd completion`** command

The `yd-*` commands, such as `yd-submit` and `yd-list`, are deprecated: they still run, with a warning, until a future release; `yd help --deprecated` says what replaces each.

The operation of the commands is controlled using TOML configuration files and/or environment variables and command-line arguments. In addition, Work Requirements and Worker Pools can be defined using JSON files providing extensive configurability.

Commands are also provided for the semi-automatic setup of cloud provider accounts for use with YellowDog, and the creation of YellowDog assets to work with these cloud provider accounts. Please see **[Cloud Wizard](README_CLOUDWIZARD.md)** for more details.

Run any command with the `--help`/`-h` option to discover the command's options.

# YellowDog Prerequisites

To submit **Work Requirements** to YellowDog for processing by Configured Worker Pools (on-premises) and/or Provisioned Worker Pools (cloud-provisioned resources), you'll need:


1. A YellowDog Platform Account.


2. An Application Key & Secret: in the **Accounts** section under the **Applications** tab in the YellowDog Portal, use the **Add Application** button to create a new Application, and make a note of its **Key** and **Secret** (these will only be displayed once).

To create **Provisioned Worker Pools**, you'll need:

3. A **Keyring** created via the YellowDog Portal, with access to Cloud Provider credentials as required. The Application must be granted access to the Keyring.


4. One or more **Compute Sources** defined, and a **Compute Requirement Template** created. The images used by instances must include the YellowDog agent, configured with the Task Type(s) to match the Work Requirements to be submitted.

To set up **Configured Worker Pools**, you'll need:

5. A Configured Worker Pool Token: from the **Workers** tab in the YellowDog Portal, use the **+Add Configured Worker Pool** button to create a new Worker Pool and generate a token.


6. Obtain the YellowDog Agent and install/configure it on your on-premises systems using the Token obtained above. See guidance for [Linux](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md) and [Windows](https://github.com/yellowdog/resources/blob/main/agent-install/windows/README-CONFIGURED.md).

# What It Looks Like

A `config.toml` holds your Application key and secret, namespace and tag (`yd init` writes them), and here a Work Requirement of three Tasks:

```toml
[workRequirement]
    taskType = "bash"
    arguments = ["-c", "echo Rendering frame {{task_number}}"]
    taskCount = 3
    workerTag = "render"
```

`yd workrequirement submit` submits it. With `--dry-run`, it shows what it would submit instead:

```text
% yd workrequirement submit --dry-run
2026-10-27 16:18:07 : Generated Work Requirement 'render_261027-1618071-ff'
2026-10-27 16:18:07 : Generated Task Group 'task_group_1'
2026-10-27 16:18:07 : Expanding number of Tasks in Task Group 'task_group_1' to 'taskCount=3' Tasks
2026-10-27 16:18:07 : DRY-RUN : Printing JSON Work Requirement specification:
{
  "namespace": "image-processing",
  "name": "render_261027-1618071-ff",
  …
```

[Typical Workflow](#typical-workflow) runs it on a Worker Pool from start to finish.

# Installation

Python 3.10 or later is required. The simplest way to install the CLI is with **[uv](https://docs.astral.sh/uv/)**, which downloads a suitable Python if you have none, and puts the `yd` command on your PATH:

```shell
uv tool install yellowdog-cli
```

To update it, run `uv tool upgrade yellowdog-cli`. For [Jsonnet](docs/jsonnet.md) support, install `"yellowdog-cli[jsonnet]"` instead.

To install uv itself, run `curl -LsSf https://astral.sh/uv/install.sh | sh` on macOS or Linux, or `winget install --id=astral-sh.uv -e` on Windows. **[Installation](docs/installation.md)** has the other ways to install uv, choosing the Python the CLI runs on, and installing into a virtual environment with uv or pip instead.

# YellowDog Commander (GUI)

Commander is an optional cross-platform desktop GUI for driving the CLI. Install it with the `commander` extra, as you installed the CLI, and launch it with `yd commander`:

```commandline
uv tool install "yellowdog-cli[commander]"      # Option 1
uv pip install -U "yellowdog-cli[commander]"    # Option 2, in the virtual environment
pip install -U "yellowdog-cli[commander]"       # Option 3, in the virtual environment
yd commander
```

It works by running `yd` commands on your behalf and displaying their output. See [`yellowdog_cli/commander/README.md`](yellowdog_cli/commander/README.md) for details.

# YellowDog MCP Server

`yd mcp` is an MCP server exposing the `yd` commands as tools for an agent. Install it with the `mcp` extra, as you installed the CLI, and launch it with `yd mcp`:

```commandline
uv tool install "yellowdog-cli[mcp]"      # Option 1
uv pip install -U "yellowdog-cli[mcp]"    # Option 2, in the virtual environment
pip install -U "yellowdog-cli[mcp]"       # Option 3, in the virtual environment
yd mcp config.toml
```

The extras can be combined, e.g. `"yellowdog-cli[jsonnet,commander,mcp]"`; the `cloudwizard` extra, for `yd cloudwizard`, is described in [`README_CLOUDWIZARD.md`](README_CLOUDWIZARD.md).

It runs `yd` commands on an agent's behalf and returns their `--json` results. See [`yellowdog_cli/mcp/README.md`](yellowdog_cli/mcp/README.md) for details.

# Usage

However it is installed, the **`yd`** command is on your PATH (for a virtual environment, while it is active). Most of its commands name an object and take a verb, `yd <noun> <verb>`, and the rest are `yd <command>`; see the [Command List](docs/commands.md).

Commands are run from the command line. Invoking any command with the `--help` or `-h` option will display the command-line options applicable to that command, e.g.:

```text
% yd workrequirement cancel -h
usage: yd workrequirement cancel [-h] [--sort <name|created|status|namespace>[,...]] [--reverse] [--variable <var1=v1>] [--namespace [<namespace>]]
                                 [--tag [<tag>]] [--abort] [--follow] [--dry-run] [--json] [--interactive] [--yes]
                                 [<work-requirement-name-or-ID> ...] [universal options]

YellowDog command-line utility for cancelling Work Requirements

positional arguments:
  <work-requirement-name-or-ID>
                        the name(s) or YellowDog ID(s) of the work requirement(s) to be cancelled; can also supply task IDs; a name may be a glob
                        pattern (e.g. 'proj-*')

options:
  -h, --help            show this help message and exit
  --sort <name|created|status|namespace>[,...]
                        order in which listed and interactively-selected entities are sorted: 'name' (default), 'created' (creation time, earliest
                        first), 'status' (status name), or 'namespace'; give several, separated by commas, to sort by each in turn (e.g.
                        'status,created'), the name always breaking any tie; combine with --reverse to invert the whole order
  --reverse             reverse (descending) the whole order --sort gives
  --variable, -v <var1=v1>
                        user-defined variable substitution; the option can be supplied multiple times, one per variable
  --namespace, -n [<namespace>]
                        the namespace to use when specifying entities; this is set to '' if the option is provided without a value
  --tag, -t [<tag>]     the tag to use when naming, tagging, or selecting entities; this is set to '' if the option is provided without a value
  --abort, -a           abort running tasks with immediate effect
  --follow, -f          follow progress after cancelling the work requirement(s)
  --dry-run, -D         list the entities that would be affected, without acting
  --json                emit the actions taken, or with --dry-run what would be taken, as a JSON array
  --interactive, -i     list, and interactively select, the items to act on
  --yes, -y             perform modifying/destructive actions without requiring user confirmation

universal options:
  --docs                provide a link to the documentation for this version
  --config, -c <config_file.toml>
                        configuration file in TOML format, whose values take precedence over environment variables, unlike a file found by default;
                        the default to use is 'config.toml' in the current directory, else ~/.config/yellowdog/config.toml
  --key, -k <app-key-id>
                        the application key ID
  --secret, -s <app-key-secret>
                        the application key secret
  --url, -u <url>       the YellowDog Platform API URL (defaults to 'https://api.yellowdog.ai')
  --debug               display the Python stack trace on error, and the configuration preamble
  --pac                 enable PAC (proxy auto-configuration) support
  --no-format, --nf     disable colouring and text wrapping in command output
  --quiet, -q           suppress (non-error, non-interactive) status and progress messages
  --env-override        values in '.env' file override values in the environment (also set via YD_ENV_OVERRIDE)
  --print-pid, --pp     include the process ID of this CLI invocation alongside timestamp in logging messages
  --no-config, --nc     ignore the contents of any TOML configuration file (even if specified on the command line)
  --property <section.key=value>
                        override a TOML configuration property; format: 'section.key=value', e.g. 'workRequirement.workerTags=["mytag"]'; can be
                        supplied multiple times
```

To start, run **[`yd init`](docs/commands.md#yd-init)**. It asks for your Application key and secret, namespace, tag and Platform URL, and writes them to a `config.toml` in the current directory:

```shell
yd init
```

With `--user`, it writes them to your own `~/.config/yellowdog/config.toml` instead, which every directory without a `config.toml` of its own reads.

For a first run from start to finish, follow the CLI track of **[Getting Started](https://docs.yellowdog.ai/#/getting-started/getting-started)** in the YellowDog Documentation.

If a command fails and the reason isn't clear, run **[`yd doctor`](docs/commands.md#yd-doctor)**: it checks the installation, the configuration, the credentials and the connection to the Platform, and suggests a remedy for anything wrong.

## Shell Completion

Tab completion of the commands, their verbs, their options and the values the CLI knows is available for bash, zsh, fish and PowerShell: add the line for your shell to its start-up file.

```shell
eval "$(yd completion bash)"     # ~/.bashrc
eval "$(yd completion zsh)"      # ~/.zshrc
yd completion fish | source      # ~/.config/fish/config.fish
```

```powershell
yd completion powershell | Out-String | Invoke-Expression    # $PROFILE
```

See [yd completion](docs/commands.md#yd-completion) for what it completes.

## Specification Schemas

Every kind of specification, and the configuration file, has a JSON Schema describing exactly what it accepts. Every run checks the file it is given against its schema and warns of what it finds; `--validate` checks a file and stops, and `yd schema --write` writes the schemas for an editor to check files against as they are written. None of this contacts the Platform. See **[Checking Specifications](docs/schemas.md)**.

## Applications That Can Read Only Some Namespaces

An Application without global read access can still find items by name. Wherever a command searches without a namespace, it searches only the namespaces the Application can read: for example, a name given without `namespace/`, or `yd list` with an empty namespace.

The Platform refuses a search across every namespace from such an Application, which is why the search is narrowed. A permission the Application lacks even in those namespaces is still reported as a missing permission (exit code 5).

## Machine-readable Output and Exit Codes

What `--json` prints, its shapes and the exit codes every command uses are described in **[Machine-readable Output and Exit Codes](docs/json-output.md)**.

# Typical Workflow

A common pattern when using YellowDog is to submit a Work Requirement and provision a Worker Pool simultaneously, then follow both to completion.

Both commands read their settings from `config.toml`. This one runs ten Bash Tasks on up to two nodes:

```toml
[common]
    # key and secret, as 'yd init' writes them
    namespace = "image-processing"
    tag = "thumbnails"

[workRequirement]
    taskType = "bash"
    arguments = ["-c", "echo Processing frame {{task_number}}"]
    taskCount = 10
    workerTag = "thumbnails"

[workerPool]
    templateId = "image-processing/ubuntu-small"
    maxNodes = 2
    workerTag = "thumbnails"
```

`templateId` names a Compute Requirement Template you have already created, by name or YellowDog ID. The [Cloud Wizard](README_CLOUDWIZARD.md) can create one for you. The matching `workerTag` values send the Tasks to this pool's Workers. The properties are described in [Work Requirements](docs/work-requirements.md) and [Worker Pools](docs/worker-pools.md).

With `--quiet`, each command prints just the YellowDog ID (YDID) of what it created, so its output can be captured in a shell script:

```bash
# Submit a Work Requirement and capture its YDID
WR_ID=$(yd workrequirement submit --quiet)

# Provision a Worker Pool and capture its YDID
WP_ID=$(yd workerpool provision --quiet)

# Follow both until the Work Requirement finishes and the Worker Pool shuts down
yd follow "$WR_ID" "$WP_ID"

# List any of its Tasks that failed
yd task list --within "$WR_ID" --status failed
```

Alternatively, `yd workrequirement submit --follow` and `yd workerpool provision` can be run in parallel, letting the Worker Pool pick up Tasks as they are submitted:

```bash
yd workerpool provision &
yd workrequirement submit --follow
```

When the Work Requirement is finished, the Worker Pool will scale down and shut itself down automatically based on the configured `idlePoolTimeout` (30 minutes by default).

Note that there is no fixed 1:1 relationship between Work Requirements and Worker Pools. The YellowDog Scheduler matches Task Groups to Workers based on the Task Group's run specification (worker tags, instance types, providers, regions, etc.) — any Worker Pool whose Workers satisfy those constraints is a candidate. This means a single Worker Pool can serve Task Groups from multiple Work Requirements simultaneously, and a single Work Requirement's Task Groups can be distributed across multiple Worker Pools.

# Documentation

Beyond this page, the documentation is one page per topic, mapped below. For a first run from start to finish, follow the CLI track of **[Getting Started](https://docs.yellowdog.ai/#/getting-started/getting-started)** in the YellowDog Documentation; help is also available for every command with `--help` or `-h`.

## Guides

| Page | What it covers |
|---|---|
| **[Installation](docs/installation.md)** | Installing the CLI with uv, or into a virtual environment with uv or pip; updating it, choosing its Python, and the Jsonnet extra |
| **[Configuration](docs/configuration.md)** | The `config.toml` file and naming rules; the properties common to every command, and setting them on the command line, in environment variables or a `.env` file; overriding any property with `--property`; and which value wins |
| **[Variable Substitutions](docs/variables.md)** | `{{variable}}` substitutions: the default variables, defining your own, type tags, defaults, removing a property with `::`, writing one literally, and the `__{{variable}}__` form for User Data and Node Actions |
| **[Work Requirements](docs/work-requirements.md)** | Defining and submitting Work Requirements: their JSON and TOML structure, property inheritance, retries and failure policies, Task templates, automatic naming, CSV data and dry runs |
| **[Worker Pools](docs/worker-pools.md)** | Provisioning Worker Pools and Compute Requirements: their properties and JSON specifications, large-scale provisioning, dry runs, and Node Actions |
| **[Data Client](docs/data-client.md)** | Moving files to, from and between object stores with `yd data`, through rclone: remote paths, named profiles, worked examples and troubleshooting |
| **[Creating, Updating and Removing YellowDog Resources](docs/resources.md)** | `yd resource create` and `remove`: templates, Keyrings and Credentials, Image Families, Allowances, Applications, Groups, Configured Worker Pools and the rest |
| **[Jsonnet Support](docs/jsonnet.md)** | Writing any specification in Jsonnet, and how variable substitutions work in it |
| **[Checking Specifications](docs/schemas.md)** | The specifications' JSON Schemas: checking a file with `--validate`, in an editor or in CI, and `yd schema` |

## Reference

| Page | What it covers |
|---|---|
| **[Command List](docs/commands.md)** | Every command, the options they share, and each command's own options and examples |
| **[Work Requirement Property Dictionary](docs/work-requirement-property-dictionary.md)** | Every Work Requirement property, its type, and the levels it can be set at |
| **[Machine-readable Output and Exit Codes](docs/json-output.md)** | What `--json` prints for each command, and the exit codes every command uses |

## Optional Extensions

| Page | What it covers |
|---|---|
| **[YellowDog Commander](yellowdog_cli/commander/README.md)** | `yd commander`, the desktop GUI that runs `yd` commands for you (the `commander` extra) |
| **[YellowDog MCP Server](yellowdog_cli/mcp/README.md)** | `yd mcp`, which gives an agent the `yd` commands as tools (the `mcp` extra) |
| **[YellowDog Cloud Wizard](README_CLOUDWIZARD.md)** | `yd cloudwizard`, which sets up a cloud provider account and the YellowDog resources that use it (the `cloudwizard` extra) |

## The Project

| Page | What it covers |
|---|---|
| **[Changelog](CHANGELOG.md)** | What changed in each release, and what to check when upgrading |
| **[Development Guide](DEVELOPMENT.md)** | Building, testing and contributing to the CLI |
