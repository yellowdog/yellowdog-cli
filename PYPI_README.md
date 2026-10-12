# Command Line Interface for the YellowDog Platform

[![PyPI version](https://img.shields.io/pypi/v/yellowdog-cli)](https://pypi.org/project/yellowdog-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/yellowdog-cli)](https://pypi.org/project/yellowdog-cli/)
[![Licence](https://img.shields.io/pypi/l/yellowdog-cli)](https://github.com/yellowdog/yellowdog-cli/blob/main/LICENSE)

## Overview

This is a set of Python CLI commands for interacting with the YellowDog Platform, also providing examples of usage of the [YellowDog Python SDK](https://docs.yellowdog.ai/sdk/python/index.html).

The CLI is one command, `yd`. Most of what it does names the object acted on, then what to do to it — `yd workrequirement submit`, `yd instance terminate` — and `yd <noun> --help` lists a noun's verbs; `yd help` lists everything. The commands support:

- **Work Requirements** — submitting, cancelling, holding, starting, finishing and reprioritising them, and comparing them against Worker Pools, with **`yd workrequirement`** (short form `yd wr`)
- **Task Groups and Tasks** — reprioritising Task Groups and comparing them against Worker Pools with **`yd taskgroup`** (`yd tg`), and aborting running Tasks with **`yd task`**
- **Worker Pools** — provisioning, resizing and shutting them down, and refreshing or regenerating Configured Worker Pools' tokens, with **`yd workerpool`** (`yd wp`)
- **Compute Requirements** — instantiating, resizing, stopping, starting, reprovisioning and terminating them with **`yd computerequirement`** (`yd cr`)
- **Instances and Nodes** — stopping, starting, restarting, deprovisioning and terminating individual Instances with **`yd instance`**, and Worker Pool Nodes' Instances with **`yd node`**, which also shuts Nodes down and submits Node Actions to them
- **Resources** — creating, updating and removing Compute Source Templates, Compute Requirement Templates, Keyrings, Credentials, Image Families, Namespaces, Allowances, Configured Worker Pools, Attribute Definitions, Namespace Policies, Groups, Applications and Users (update only) with **`yd resource`**
- **Allowances** — boosting them with **`yd allowance`**
- **Remote data stores** — uploading, downloading, listing, deleting and copying files with **`yd data`**
- **Cloud provider setup** (AWS, Azure, GCP) with the **`yd cloudwizard`** command
- **Cloud regions, instance types and prices**, as the YellowDog Platform knows them, with **`yd cloudinfo`**
- **Inspecting** — listing YellowDog items with **`yd list`**, showing any entity's details by its YellowDog ID with **`yd show`**, following event streams with **`yd follow`**, and waiting for Work Requirements, Worker Pools or Compute Requirements to finish with **`yd wait`**; every noun also has `list` and `show` verbs for its own objects
- **Showing** the details of the current Application with the **`yd application`** command
- **Diagnosing** the configuration, credentials and connectivity with the **`yd doctor`** command
- **Reporting** the processed values of variable substitutions with the **`yd variables`** command
- **Completing** commands, verbs, options and their values on Tab, in bash, zsh, fish and PowerShell, with the **`yd completion`** command

Utility commands are also provided: **`yd completion`**, **`yd doctor`**, **`yd format-json`**, **`yd help`**, **`yd jsonnet2json`**, **`yd schema`**, and **`yd version`**. For a full list of commands run **`yd help`**.

The remote data store commands — the `yd data` verbs `upload`, `download`, `delete`, `ls` and `copy` — use **[rclone](https://rclone.org)**, and do not require YellowDog credentials. An `rclone` binary already on your `PATH` is used in preference and is never modified; otherwise one is downloaded to a per-user cache directory the first time it's needed.

## Installation

Python 3.10 or later is required.

**pipx (recommended)** — installs into an isolated environment and puts the commands on your PATH automatically:

```shell
pipx install yellowdog-cli
```

**uv:**

```shell
uv tool install yellowdog-cli
```

**pip + virtual environment:**

```shell
python3 -m venv yd-env
source yd-env/bin/activate   # macOS / Linux; on Windows: yd-env\Scripts\activate
pip install -U yellowdog-cli
```

### Optional Extras

Four optional extras are available:

| Extra         | Provides                                                         |
|---------------|------------------------------------------------------------------|
| `jsonnet`     | Jsonnet templating of resource specifications                    |
| `commander`   | The `yd commander` desktop GUI, described below                  |
| `cloudwizard` | The cloud provider SDKs required by the `yd cloudwizard` command |
| `mcp`         | The `yd mcp` MCP server, described below                         |

List the ones you need in square brackets at installation time, e.g. to install all four:

```shell
pipx install "yellowdog-cli[jsonnet,commander,cloudwizard,mcp]"    # pipx
uv tool install "yellowdog-cli[jsonnet,commander,cloudwizard,mcp]" # uv
pip install -U "yellowdog-cli[jsonnet,commander,cloudwizard,mcp]"  # pip
```

An extra can also be added to an existing pipx installation without reinstalling it, e.g. `pipx inject yellowdog-cli jsonnet`.

### Commander GUI

**`yd commander`** is an optional cross-platform desktop GUI for driving the CLI, installed via the `commander` extra above:

```shell
pip install -U "yellowdog-cli[commander]"
yd commander
```

It works by running `yd` commands on your behalf and displaying their output. See the [Commander documentation](https://github.com/yellowdog/yellowdog-cli/blob/main/yellowdog_cli/commander/README.md) for details.

### MCP Server

**`yd mcp`** is an optional MCP server exposing the `yd` commands as tools for an agent, installed via the `mcp` extra above:

```shell
pip install -U "yellowdog-cli[mcp]"
yd mcp config.toml
```

It runs `yd` commands on an agent's behalf, with `--json`, and returns their results. See the [MCP server documentation](https://github.com/yellowdog/yellowdog-cli/blob/main/yellowdog_cli/mcp/README.md) for details.

## Documentation

Please see the documentation in the [GitHub repository](https://github.com/yellowdog/yellowdog-cli) for full details. This documentation should be read in conjunction with the main **[YellowDog Documentation](https://docs.yellowdog.ai)**.
