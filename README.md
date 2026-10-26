# YellowDog Command-Line Interface

<!--ts-->
* [Overview](#overview)
* [YellowDog Prerequisites](#yellowdog-prerequisites)
* [Installation](#installation)
   * [Installing uv](#installing-uv)
   * [Option 1: uv tool](#option-1-uv-tool)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli)
      * [Update](#update)
      * [With Jsonnet support](#with-jsonnet-support)
   * [Option 2: a virtual environment created with uv](#option-2-a-virtual-environment-created-with-uv)
      * [Create and activate a virtual environment](#create-and-activate-a-virtual-environment)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli-1)
      * [Update](#update-1)
      * [With Jsonnet support](#with-jsonnet-support-1)
   * [Option 3: pip in a virtual environment](#option-3-pip-in-a-virtual-environment)
      * [Create and activate a virtual environment](#create-and-activate-a-virtual-environment-1)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli-2)
      * [Update](#update-2)
      * [With Jsonnet support](#with-jsonnet-support-2)
* [YellowDog Commander (GUI)](#yellowdog-commander-gui)
* [YellowDog MCP Server](#yellowdog-mcp-server)
* [Usage](#usage)
   * [Shell Completion](#shell-completion)
   * [Specification Schemas](#specification-schemas)
   * [Machine-readable Output and Exit Codes](#machine-readable-output-and-exit-codes)
* [Typical Workflow](#typical-workflow)
* [Documentation](#documentation)
   * [Configuration](#configuration)
   * [Variable Substitutions](#variable-substitutions)
   * [Work Requirements](#work-requirements)
   * [Worker Pools](#worker-pools)
   * [Data Client](#data-client)
   * [Creating, Updating and Removing YellowDog Resources](#creating-updating-and-removing-yellowdog-resources)
   * [Jsonnet Support](#jsonnet-support)
   * [Command List](#command-list)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Oct 26 08:11:21 GMT 2026 -->

<!--te-->

# Overview

This repository contains a set of command-line utilities for driving the YellowDog Platform, written in Python. The commands use the **[YellowDog Python SDK](https://docs.yellowdog.ai/sdk/python/index.html)**, the code for which can be found [on GitHub](https://github.com/yellowdog/yellowdog-sdk-python-public).

This documentation should be read in conjunction with the main **[YellowDog Documentation](https://docs.yellowdog.ai)**, which provides a comprehensive description of the concepts and operation of the YellowDog Platform.

The CLI is one command, `yd`. Most of what it does names the object acted on, then what to do to it — `yd workrequirement submit`, `yd instance terminate` — and `yd <noun> --help` lists a noun's verbs; `yd` alone, or `yd help`, lists everything. The commands provide the following capabilities:

- **Work Requirements** — submitting, cancelling, holding, starting, finishing and reprioritising them, and comparing them against Worker Pools, with **`yd workrequirement`** (short form `yd wr`)
- **Task Groups and Tasks** — reprioritising Task Groups and comparing them against Worker Pools with **`yd taskgroup`** (`yd tg`), and aborting running Tasks with **`yd task`**
- **Worker Pools** — provisioning, resizing and shutting them down, and refreshing or regenerating Configured Worker Pools' tokens, with **`yd workerpool`** (`yd wp`)
- **Compute Requirements** — instantiating, resizing, stopping, starting, reprovisioning, terminating and setting when they are automatically terminated with **`yd computerequirement`** (`yd cr`)
- **Instances and Nodes** — stopping, starting, restarting, deprovisioning and terminating individual Instances with **`yd instance`**, and Worker Pool Nodes' Instances with **`yd node`**, which also shuts Nodes down and submits Node Actions to them
- **Resources** — creating, updating and removing Compute Source Templates, Compute Requirement Templates, Keyrings, Credentials, Image Families, Namespaces, Allowances, Configured Worker Pools, Attribute Definitions, Namespace Policies, Groups, Applications and Users (update only) with **`yd resource`**, from specification files or, for a resource of a few properties, on the command line (`yd resource create --type Keyring --set name=team-keys`), and showing or removing them by name
- **Allowances** — boosting them with **`yd allowance`**
- **Remote data stores** — uploading, downloading, listing, deleting and copying files with **`yd data`**
- **Cloud regions, instance types and prices**, as the YellowDog Platform knows them, with **`yd cloudinfo`**
- **Inspecting** — listing YellowDog items with **`yd list`**, filtered by name, status or provider, or within one Work Requirement, Task Group, Compute Requirement, Worker Pool or Node (`yd task list --within <wr>`), the largest listings stopping at 1000 items unless `--limit` says otherwise, showing any entity's details by its YellowDog ID with **`yd show`**, following event streams with **`yd follow`**, and waiting for Work Requirements, Worker Pools or Compute Requirements to finish with **`yd wait`**; every noun also has `list` and `show` verbs for its own objects
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

# Installation

Python 3.10 or later is required. There are several ways to install the CLI, each keeping it and its dependencies in an environment of their own; choose the one that fits how you work:

- **[uv tool](#option-1-uv-tool)** — the commands on your PATH everywhere, with no environment to activate. uv supplies Python itself if you have none.
- **[A virtual environment created with uv](#option-2-a-virtual-environment-created-with-uv)** — an environment you activate, for using the CLI alongside other Python tools. uv supplies Python itself if you have none.
- **[pip in a virtual environment](#option-3-pip-in-a-virtual-environment)** — the standard Python tooling, with a Python you have installed.

Other installers, such as pipx, work too.

## Installing uv

**[uv](https://docs.astral.sh/uv/)** installs Python packages, and Python itself: the first two options need it, and no Python of your own. See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for full instructions. Quick options:

| Platform         | Command                                            |
|------------------|----------------------------------------------------|
| macOS / Linux    | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| macOS (Homebrew) | `brew install uv`                                  |
| Windows          | `winget install --id=astral-sh.uv -e`              |

## Option 1: uv tool

uv installs the CLI into an environment of its own and puts the `yd` command on your PATH, downloading a suitable Python if none is installed.

### Install the YellowDog CLI

```shell
uv tool install yellowdog-cli
```

To choose the Python it runs on, which uv downloads if it is not installed:

```shell
uv tool install --python 3.14 yellowdog-cli
```

### Update

```shell
uv tool upgrade yellowdog-cli
```

### With Jsonnet support

```shell
uv tool install "yellowdog-cli[jsonnet]"
```

## Option 2: a virtual environment created with uv

uv creates the virtual environment, downloading the Python you ask for if it is not installed, and installs the CLI into it.

### Create and activate a virtual environment

```shell
uv venv --python 3.14 yd-env
source yd-env/bin/activate   # macOS / Linux
yd-env\Scripts\activate      # Windows
```

### Install the YellowDog CLI

```shell
uv pip install yellowdog-cli
```

### Update

```shell
uv pip install -U yellowdog-cli
```

### With Jsonnet support

```shell
uv pip install -U "yellowdog-cli[jsonnet]"
```

> **Note:** You will need to activate the virtual environment (`source yd-env/bin/activate`) each time you open a new terminal session, or add the activation to your shell profile.

## Option 3: pip in a virtual environment

This uses the standard Python tooling, with a Python you have installed. If you don't have Python 3.10 or later, download it from **[python.org](https://www.python.org/downloads/)**, or use your system package manager:

| Platform        | Command                             |
|-----------------|-------------------------------------|
| macOS           | `brew install python`               |
| Ubuntu / Debian | `sudo apt install python3`          |
| Windows         | `winget install Python.Python.3.12` |

### Create and activate a virtual environment

```shell
python3 -m venv yd-env
source yd-env/bin/activate   # macOS / Linux
yd-env\Scripts\activate      # Windows
```

### Install the YellowDog CLI

```shell
pip install -U yellowdog-cli
```

### Update

```shell
pip install -U yellowdog-cli
```

### With Jsonnet support

```shell
pip install -U "yellowdog-cli[jsonnet]"
```

> **Note:** As with uv's, you will need to activate the virtual environment each time you open a new terminal session, or add the activation to your shell profile.

# YellowDog Commander (GUI)

Commander is an optional cross-platform desktop GUI for driving the CLI. Install it with the `commander` extra and launch it with `yd commander`:

```commandline
pip install -U "yellowdog-cli[commander]"
yd commander
```

It works by running `yd` commands on your behalf and displaying their output. See [`yellowdog_cli/commander/README.md`](yellowdog_cli/commander/README.md) for details.

# YellowDog MCP Server

`yd mcp` is an MCP server exposing the `yd` commands as tools for an agent. Install it with the `mcp` extra and launch it with `yd mcp`:

```commandline
pip install -U "yellowdog-cli[mcp]"
yd mcp config.toml
```

It runs `yd` commands on an agent's behalf and returns their `--json` results. See [`yellowdog_cli/mcp/README.md`](yellowdog_cli/mcp/README.md) for details.

# Usage

All three installation methods add the **`yd`** command to your PATH. Most of its commands name an object and take a verb, `yd <noun> <verb>`, and the rest are `yd <command>`; see the [Command List](docs/commands.md).

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
                        configuration file in TOML format; the default to use is 'config.toml' in the current directory, else
                        ~/.config/yellowdog/config.toml
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

To start, run **[`yd init`](docs/commands.md#yd-init)**: it asks for your Application key and secret, namespace and tag, and writes them to a `config.toml` in the current directory, or with `--user` to your own `~/.config/yellowdog/config.toml`, which every directory without a `config.toml` of its own reads.

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

A Work Requirement, Worker Pool, Compute Requirement, resource, or Node Action specification each has a JSON Schema describing exactly what it accepts, and the `yd schema` command prints, writes or checks them (see [yd schema](docs/commands.md#yd-schema)). Every property the CLI itself defines is described from the CLI's own reference for it, such as the [Work Requirement Property Dictionary](docs/property-dictionary.md#work-requirement-property-dictionary); every other property is described from the installed YellowDog SDK. Upgrading either the CLI or the SDK can therefore change a schema, so re-run `yd schema --write <dir>` afterwards, or `yd schema --check <dir>` first to see whether it is needed. The TOML configuration file has a schema too, `config`, which every command checks the file against (see [Configuration](docs/configuration.md#configuration)).

Point an editor's JSON Schema support at the files `yd schema --write` produces, to get inline validation and autocomplete while writing a specification. In VS Code, add an entry to `settings.json`:

```json
"json.schemas": [
  {
    "fileMatch": ["*.wr.json", "work-requirement*.json"],
    "url": "./schemas/work-requirement.schema.json"
  }
]
```

A specification file can instead name its own schema directly, with a `$schema` key at the top of the file; the CLI accepts this key and ignores it, so it is never sent on to the Platform. JetBrains IDEs offer the same association under Preferences → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings.

Every run of `yd workrequirement submit`, `yd workerpool provision`, `yd computerequirement instantiate`, `yd resource create` and `yd node action` checks the specification it is given against its schema, and warns of each violation it finds, naming the file and where in it the violation is, without stopping; the Platform, or the CLI's own processing, still has the final say on whether the specification is accepted. If a schema cannot be built from the installed SDK, the run warns once that the file went unchecked and carries on as it would without a schema, and `yd schema` with that specification's type shows why.

`--validate` checks the specification and stops there instead of continuing: it prints every violation and exits with a non-zero status, or reports the file valid and exits zero; under `--json` its result is the array of violations, an empty array for a valid file. It is refused wherever there is no specification file to check against a schema, and together with `--json-raw` or `--status`, neither of which names one.

To keep the check quick, each schema is compiled once and kept, a file of up to about 1MB per schema, in a directory of your own under the system's temporary directory (`yellowdog-cli-schemas-<uid>`, or `yellowdog-cli-schemas` on Windows), where the operating system's routine clean-up removes it; it is compiled again whenever the CLI or the SDK changes, and deleting the directory is always safe. If the directory cannot be used (e.g., it is open to other users), the schemas are compiled on every run instead, and `--debug` says why.

A `{{variable}}` substitution, the `{{name::}}` unset form included, is accepted wherever a plain value is otherwise expected, because a specification is checked after its variables have already been substituted, so an unresolved reference is never itself reported as a violation. One consequence of this: a resource's `resource` property, or a Node Action's `type` property, chooses which further properties are checked, so a `{{variable}}` left unresolved there means the rest of that resource or action is not checked either. A Jsonnet or TOML specification is checked after it has been converted to JSON, so an editor validates the JSON that conversion produces rather than the source file itself; run `yd jsonnet2json` on a Jsonnet file to see that JSON.

**Applications that can read only some namespaces.** Wherever a command searches without a namespace — a name given without `namespace/`, or `yd list` with an empty namespace — it searches the namespaces the Application can read rather than every namespace, since the platform refuses a search across every namespace from an Application without global read access. A permission the Application lacks even in those namespaces is still reported as a missing permission (exit code 5).

## Machine-readable Output and Exit Codes

What `--json` prints, its shapes and the exit codes every command uses are described in **[Machine-readable Output and Exit Codes](docs/json-output.md)**.

# Typical Workflow

A common pattern when using YellowDog is to submit a Work Requirement and provision a Worker Pool simultaneously, then follow both to completion. The `--quiet` flag returns just the YDID, making it easy to compose commands in shell scripts:

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

When the Work Requirement is finished, the Worker Pool will scale down and shut itself down automatically based on the configured `idlePoolTimeout`.

Note that there is no fixed 1:1 relationship between Work Requirements and Worker Pools. The YellowDog Scheduler matches Task Groups to Workers based on the Task Group's run specification (worker tags, instance types, providers, regions, etc.) — any Worker Pool whose Workers satisfy those constraints is a candidate. This means a single Worker Pool can serve Task Groups from multiple Work Requirements simultaneously, and a single Work Requirement's Task Groups can be distributed across multiple Worker Pools.

# Documentation

Beyond this page, the documentation is in the `docs` directory, one page per topic, each introduced below. Machine-readable output and exit codes, under [Usage](#usage) above, have a page of their own too.

## Configuration

The configuration file, naming rules and the properties common to every command are described in **[Configuration](docs/configuration.md)**.

## Variable Substitutions

Variables, their defaults and where they can be used are described in **[Variable Substitutions](docs/variables.md)**.

## Work Requirements

Defining and submitting Work Requirements, from their JSON structure and inheritance to CSV data and dry runs, is described in **[Work Requirements](docs/work-requirements.md)**.

## Worker Pools

Provisioning Worker Pools and Compute Requirements, and Node Actions, are described in **[Worker Pools](docs/worker-pools.md)**.

## Data Client

Configuring the data client, which moves files to and from object storage, is described in **[Data Client](docs/data-client.md)**.

## Creating, Updating and Removing YellowDog Resources

Creating, updating and removing resources such as templates, Keyrings, Image Families and Applications is described in **[Creating, Updating and Removing YellowDog Resources](docs/resources.md)**.

## Jsonnet Support

Writing specifications in Jsonnet is described in **[Jsonnet Support](docs/jsonnet.md)**.

## Command List

The commands, the options they share and each command's own options and examples are described in the **[Command List](docs/commands.md)**. Help is also available for every command with `--help` or `-h`.
