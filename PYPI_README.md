# Command Line Interface for the YellowDog Platform

[![PyPI version](https://img.shields.io/pypi/v/yellowdog-cli)](https://pypi.org/project/yellowdog-cli/)
[![Python versions](https://img.shields.io/pypi/pyversions/yellowdog-cli)](https://pypi.org/project/yellowdog-cli/)
[![Licence](https://img.shields.io/pypi/l/yellowdog-cli)](https://github.com/yellowdog/yellowdog-cli/blob/main/LICENSE)

## Overview

This is a set of Python CLI commands for interacting with the YellowDog Platform, also providing examples of usage of the [YellowDog Python SDK](https://docs.yellowdog.ai/sdk/python/index.html).

The commands support:

- **Aborting** running Tasks with the **`yd-abort`** command
- **Boosting** Allowances with the **`yd-boost`** command
- **Cancelling** Work Requirements with the **`yd-cancel`** command
- **Cloud provider setup** (AWS, Azure, GCP) with the **`yd-cloudwizard`** command
- **Comparing** whether Worker Pools are a match for Task Groups with the **`yd-compare`** command
- **Copying** files between remote data stores with the **`yd-copy`** command
- **Creating, Updating and Removing** Compute Source Templates, Compute Requirement Templates, Keyrings, Credentials, Image Families, Allowances, Configured Worker Pools, User Attributes, Namespace Policies, Groups, and Applications with the **`yd-create`** and **`yd-remove`** commands
- **Deleting** files from a remote data store with the **`yd-delete`** command (also available as **`yd-rm`**)
- **Downloading** files from a remote data store with the **`yd-download`** command
- **Finishing** Work Requirements with the **`yd-finish`** command
- **Following Event Streams** for Work Requirements, Worker Pools and Compute Requirements with the **`yd-follow`** command
- **Instantiating** Compute Requirements with the **`yd-instantiate`** command
- **Listing** YellowDog items using the **`yd-list`** command
- **Listing** remote data store contents with the **`yd-ls`** command
- **Provisioning** Worker Pools with the **`yd-provision`** command
- **Resizing** Worker Pools and Compute Requirements with the **`yd-resize`** command
- **Showing** the details of any YellowDog entity using its YellowDog ID with the **`yd-show`** command
- **Showing** the details of the current Application with the **`yd-application`** command
- **Shutting Down** Worker Pools and Nodes with the **`yd-shutdown`** command
- **Starting** HELD Work Requirements and **Holding** (or pausing) RUNNING Work Requirements with the **`yd-start`** and **`yd-hold`** commands
- **Stopping**, **Starting** and **Restarting** Compute Requirements and Instances with the **`yd-compute-stop`**, **`yd-compute-start`** and **`yd-compute-restart`** commands
- **Submitting** Work Requirements with the **`yd-submit`** command
- **Submitting Node Actions** to Worker Pool nodes with the **`yd-nodeaction`** command
- **Terminating** Compute Requirements with the **`yd-terminate`** command
- **Uploading** files to a remote data store with the **`yd-upload`** command
- **Waiting** for Work Requirements, Worker Pools or Compute Requirements to reach a terminal state with the **`yd-wait`** command

Utility commands are also provided: **`yd-format-json`**, **`yd-help`**, **`yd-jsonnet2json`**, and **`yd-version`**. For a full list of commands run **`yd-help`**.

The remote data store commands — `yd-upload`, `yd-download`, `yd-delete`/`yd-rm`, `yd-ls` and `yd-copy` — use **[rclone](https://rclone.org)**, and do not require YellowDog credentials. An `rclone` binary already on your `PATH` is used in preference and is never modified; otherwise one is downloaded to a per-user cache directory the first time it's needed.

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

Three optional extras are available:

| Extra         | Provides                                                         |
|---------------|------------------------------------------------------------------|
| `jsonnet`     | Jsonnet templating of resource specifications                    |
| `commander`   | The `yd-commander` desktop GUI, described below                  |
| `cloudwizard` | The cloud provider SDKs required by the `yd-cloudwizard` command |

List the ones you need in square brackets at installation time, e.g. to install all three:

```shell
pipx install "yellowdog-cli[jsonnet,commander,cloudwizard]"    # pipx
uv tool install "yellowdog-cli[jsonnet,commander,cloudwizard]" # uv
pip install -U "yellowdog-cli[jsonnet,commander,cloudwizard]"  # pip
```

An extra can also be added to an existing pipx installation without reinstalling it, e.g. `pipx inject yellowdog-cli jsonnet`.

### Commander GUI

**`yd-commander`** is an optional cross-platform desktop GUI for driving the CLI, installed via the `commander` extra above:

```shell
pip install -U "yellowdog-cli[commander]"
yd-commander
```

It works by invoking the `yd-*` commands on your behalf and displaying their output. See the [Commander documentation](https://github.com/yellowdog/yellowdog-cli/blob/main/yellowdog_cli/commander/README.md) for details.

## Documentation

Please see the documentation in the [GitHub repository](https://github.com/yellowdog/yellowdog-cli) for full details. This documentation should be read in conjunction with the main **[YellowDog Documentation](https://docs.yellowdog.ai)**.
