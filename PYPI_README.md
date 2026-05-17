# Command Line Interface for the YellowDog Platform

## Overview

This is a set of Python CLI commands for interacting with the YellowDog Platform, also providing examples of usage of the [YellowDog Python SDK](https://docs.yellowdog.ai/sdk/python/index.html).

The commands support:

- **Aborting** running Tasks with the **`yd-abort`** command
- **Boosting** Allowances with the **`yd-boost`** command
- **Cancelling** Work Requirements with the **`yd-cancel`** command
- **Comparing** whether Worker Pools are a match for Task Groups with the **`yd-compare`** command
- **Creating, Updating and Removing** Compute Source Templates, Compute Requirement Templates, Keyrings, Credentials, Image Families, Allowances, Configured Worker Pools, User Attributes, Namespace Policies, Groups, and Applications with the **`yd-create`** and **`yd-remove`** commands
- **Copying** files between remote data stores with the **`yd-copy`** command
- **Deleting** files from a remote data store with the **`yd-delete`** command
- **Downloading** files from a remote data store with the **`yd-download`** command
- **Finishing** Work Requirements with the **`yd-finish`** command
- **Following Event Streams** for Work Requirements, Worker Pools and Compute Requirements with the **`yd-follow`** command
- **Waiting** for Work Requirements, Worker Pools or Compute Requirements to reach a terminal state with the **`yd-wait`** command
- **Instantiating** Compute Requirements with the **`yd-instantiate`** command
- **Listing** YellowDog items using the **`yd-list`** command
- **Listing** remote data store contents with the **`yd-ls`** command
- **Provisioning** Worker Pools with the **`yd-provision`** command
- **Resizing** Worker Pools and Compute Requirements with the **`yd-resize`** command
- **Showing** the details of any YellowDog entity using its YellowDog ID with the **`yd-show`** command
- **Showing** the details of the current Application with the **`yd-application`** command
- **Shutting Down** Worker Pools and Nodes with the **`yd-shutdown`** command
- **Submitting Node Actions** to Worker Pool nodes with the **`yd-nodeaction`** command
- **Starting** HELD Work Requirements and **Holding** (or pausing) RUNNING Work Requirements with the **`yd-start`** and **`yd-hold`** commands
- **Submitting** Work Requirements with the **`yd-submit`** command
- **Terminating** Compute Requirements with the **`yd-terminate`** command
- **Uploading** files to a remote data store with the **`yd-upload`** command
- **Cloud provider setup** (AWS, Azure, GCP) with the **`yd-cloudwizard`** command

Utility commands are also provided: **`yd-format-json`**, **`yd-help`**, **`yd-jsonnet2json`**, and **`yd-version`**. For a full list of commands run **`yd-help`**.

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
pip install yellowdog-cli
```

To add optional Jsonnet support:

```shell
pipx inject yellowdog-cli jsonnet   # pipx
uv tool install "yellowdog-cli[jsonnet]"   # uv
pip install "yellowdog-cli[jsonnet]"       # pip
```

## Documentation

Please see the documentation in the [GitHub repository](https://github.com/yellowdog/yellowdog-cli) for full details.
