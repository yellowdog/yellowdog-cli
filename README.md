# YellowDog Command Line Interface

<!--ts-->
* [YellowDog Command Line Interface](#yellowdog-command-line-interface)
* [Overview](#overview)
* [YellowDog Prerequisites](#yellowdog-prerequisites)
* [Installation](#installation)
   * [Option 1: pipx (recommended)](#option-1-pipx-recommended)
      * [Install pipx](#install-pipx)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli)
      * [Update](#update)
      * [With Jsonnet support](#with-jsonnet-support)
   * [Option 2: uv](#option-2-uv)
      * [Install uv](#install-uv)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli-1)
      * [Update](#update-1)
      * [With Jsonnet support](#with-jsonnet-support-1)
   * [Option 3: pip + virtual environment](#option-3-pip--virtual-environment)
      * [Create and activate a virtual environment](#create-and-activate-a-virtual-environment)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli-2)
      * [Update](#update-2)
      * [With Jsonnet support](#with-jsonnet-support-2)
* [Usage](#usage)
* [Typical Workflow](#typical-workflow)
* [Configuration](#configuration)
* [Naming Rules](#naming-rules)
* [Common Properties](#common-properties)
   * [Importing common Properties](#importing-common-properties)
   * [HTTPS Proxy Support](#https-proxy-support)
   * [Specifying Common Properties using the Command Line or Environment Variables](#specifying-common-properties-using-the-command-line-or-environment-variables)
   * [Overriding Arbitrary TOML Properties on the Command Line](#overriding-arbitrary-toml-properties-on-the-command-line)
   * [Support for .env Files](#support-for-env-files)
   * [Variable Substitutions in Common Properties](#variable-substitutions-in-common-properties)
* [Variable Substitutions](#variable-substitutions)
   * [Default Variables](#default-variables)
   * [User-Defined Variables](#user-defined-variables)
      * [Variable Naming](#variable-naming)
      * [Setting Variable Values](#setting-variable-values)
      * [Precedence Order](#precedence-order)
      * [Nested Variables](#nested-variables)
      * [Providing Default Values for User-Defined Variables](#providing-default-values-for-user-defined-variables)
      * [Removing Properties Using the Unset Suffix](#removing-properties-using-the-unset-suffix)
   * [Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data](#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data)
* [Work Requirements](#work-requirements)
   * [Work Requirement JSON File Structure](#work-requirement-json-file-structure)
   * [Property Inheritance](#property-inheritance)
   * [Work Requirement Property Dictionary](#work-requirement-property-dictionary)
   * [Automatic `taskTypes` Population](#automatic-tasktypes-population)
   * [Task Retries and Failure Policies](#task-retries-and-failure-policies)
   * [Merging Additional Environment Variables into Tasks](#merging-additional-environment-variables-into-tasks)
      * [Example — TOML](#example--toml)
      * [Example — JSON](#example--json)
   * [Argument Prefix and Postfix](#argument-prefix-and-postfix)
      * [Example — TOML](#example--toml-1)
      * [Example — JSON](#example--json-1)
   * [Task Templates](#task-templates)
      * [Example — TOML](#example--toml-2)
      * [Example — JSON](#example--json-2)
   * [Automatic Properties](#automatic-properties)
      * [Work Requirement, Task Group and Task Naming](#work-requirement-task-group-and-task-naming)
         * [Obtaining Names/Context from Environment Variables at Task Run Time](#obtaining-namescontext-from-environment-variables-at-task-run-time)
      * [Task and Task Group Counts](#task-and-task-group-counts)
   * [Examples](#examples)
      * [TOML Properties in the workRequirement Section](#toml-properties-in-the-workrequirement-section)
      * [JSON Properties at the Work Requirement Level](#json-properties-at-the-work-requirement-level)
      * [JSON Properties at the Task Group Level](#json-properties-at-the-task-group-level)
      * [JSON Properties at the Task Level](#json-properties-at-the-task-level)
   * [Variable Substitutions in Work Requirement Properties](#variable-substitutions-in-work-requirement-properties)
      * [Work Requirement Name Substitution](#work-requirement-name-substitution)
      * [Task and Task Group Name Substitutions](#task-and-task-group-name-substitutions)
   * [Dry-Running Work Requirement Submissions](#dry-running-work-requirement-submissions)
      * [Adding Task Groups and Tasks to an Existing Work Requirement](#adding-task-groups-and-tasks-to-an-existing-work-requirement)
      * [Submitting 'Raw' JSON Work Requirement Specifications](#submitting-raw-json-work-requirement-specifications)
   * [Using the YellowDog Data Client](#using-the-yellowdog-data-client)
      * [Specifying Data Client Inputs](#specifying-data-client-inputs)
      * [Automatic Upload of Local Files](#automatic-upload-of-local-files)
      * [Rclone Authentication](#rclone-authentication)
      * [Specifying Data Client Outputs](#specifying-data-client-outputs)
   * [Task Execution Context](#task-execution-context)
      * [Task Execution Steps](#task-execution-steps)
      * [The User and Group used for Tasks](#the-user-and-group-used-for-tasks)
      * [Home Directory for yd-agent](#home-directory-for-yd-agent)
      * [Task Execution Directory](#task-execution-directory)
   * [Specifying Work Requirements using CSV Data](#specifying-work-requirements-using-csv-data)
      * [Work Requirement CSV Data Example](#work-requirement-csv-data-example)
      * [CSV Variable Substitutions](#csv-variable-substitutions)
      * [Property Inheritance](#property-inheritance-1)
      * [Multiple Task Groups using Multiple CSV Files](#multiple-task-groups-using-multiple-csv-files)
      * [Using CSV Data with Simple, TOML-Only Work Requirement Specifications](#using-csv-data-with-simple-toml-only-work-requirement-specifications)
      * [Inspecting the Results of CSV Variable Substitution](#inspecting-the-results-of-csv-variable-substitution)
* [Worker Pools](#worker-pools)
   * [Worker Pools vs. Compute Requirements](#worker-pools-vs-compute-requirements)
   * [Worker Pool Properties](#worker-pool-properties)
   * [Using Textual Names instead of IDs for Compute Requirement Templates and Image Families](#using-textual-names-instead-of-ids-for-compute-requirement-templates-and-image-families)
   * [Large-Scale Provisioning](#large-scale-provisioning)
   * [Automatic Properties](#automatic-properties-1)
   * [TOML Properties in the workerPool Section](#toml-properties-in-the-workerpool-section)
   * [Worker Pool Specification Using JSON Documents](#worker-pool-specification-using-json-documents)
      * [Worker Pool JSON Examples](#worker-pool-json-examples)
      * [TOML Properties Inherited by Worker Pool JSON Specifications](#toml-properties-inherited-by-worker-pool-json-specifications)
   * [Variable Substitutions in Worker Pool Properties](#variable-substitutions-in-worker-pool-properties)
   * [Dry-Running Worker Pool Provisioning](#dry-running-worker-pool-provisioning)
   * [Node Actions](#node-actions)
      * [Action Types](#action-types)
      * [Spec File Structure](#spec-file-structure)
         * [Actions](#actions)
         * [Action Groups](#action-groups)
      * [Action Fields Reference](#action-fields-reference)
         * [Common Fields (all action types)](#common-fields-all-action-types)
      * [Node Selection](#node-selection)
      * [Worker Pool Selection](#worker-pool-selection)
      * [Checking Node Action Queue Status](#checking-node-action-queue-status)
      * [Following Progress](#following-progress)
* [Data Client](#data-client)
   * [Named Profiles](#named-profiles)
   * [Variable Substitutions for Data Client Properties](#variable-substitutions-for-data-client-properties)
   * [yd-upload](#yd-upload)
   * [yd-download](#yd-download)
   * [yd-delete](#yd-delete)
   * [yd-ls](#yd-ls)
   * [yd-copy](#yd-copy)
* [Creating, Updating and Removing YellowDog Resources](#creating-updating-and-removing-yellowdog-resources)
   * [Overview of Operation](#overview-of-operation)
      * [Resource Creation](#resource-creation)
      * [Resource Update](#resource-update)
      * [Resource Removal](#resource-removal)
      * [Resource Matching](#resource-matching)
   * [Resource Specification Definitions](#resource-specification-definitions)
   * [Generating Resource Specifications using yd-list](#generating-resource-specifications-using-yd-list)
      * [Usage Scenario: Moving or Copying Resources to a New Namespace](#usage-scenario-moving-or-copying-resources-to-a-new-namespace)
   * [Preprocessing Resource Specifications](#preprocessing-resource-specifications)
   * [Keyrings](#keyrings)
   * [Credentials](#credentials)
   * [Compute Source Templates](#compute-source-templates)
   * [Compute Requirement Templates](#compute-requirement-templates)
   * [Image Families](#image-families)
   * [Configured Worker Pools](#configured-worker-pools)
   * [Allowances](#allowances)
   * [Attribute Definitions](#attribute-definitions)
      * [String Attribute Definitions](#string-attribute-definitions)
      * [Numeric Attribute Definitions](#numeric-attribute-definitions)
   * [Namespace Policies](#namespace-policies)
   * [Groups](#groups)
   * [Applications](#applications)
      * [Granting Keyring Access](#granting-keyring-access)
      * [Creating and Regenerating Application Keys](#creating-and-regenerating-application-keys)
   * [Users](#users)
   * [Namespaces](#namespaces)
* [Jsonnet Support](#jsonnet-support)
   * [Jsonnet Installation](#jsonnet-installation)
   * [Variable Substitutions in Jsonnet Files](#variable-substitutions-in-jsonnet-files)
   * [Checking Jsonnet Processing](#checking-jsonnet-processing)
   * [Jsonnet Example](#jsonnet-example)
* [Command List](#command-list)
   * [yd-submit](#yd-submit)
   * [yd-provision](#yd-provision)
   * [yd-cancel](#yd-cancel)
   * [yd-abort](#yd-abort)
   * [yd-shutdown](#yd-shutdown)
   * [yd-nodeaction](#yd-nodeaction)
   * [yd-instantiate](#yd-instantiate)
      * [Test-Running a Dynamic Template](#test-running-a-dynamic-template)
   * [yd-terminate](#yd-terminate)
   * [yd-compute-stop](#yd-compute-stop)
   * [yd-compute-start](#yd-compute-start)
   * [yd-compute-restart](#yd-compute-restart)
   * [yd-list](#yd-list)
   * [yd-resize](#yd-resize)
   * [yd-create](#yd-create)
   * [yd-remove](#yd-remove)
   * [yd-follow](#yd-follow)
   * [yd-wait](#yd-wait)
   * [yd-start](#yd-start)
   * [yd-hold](#yd-hold)
   * [yd-boost](#yd-boost)
   * [yd-show](#yd-show)
   * [yd-compare](#yd-compare)
   * [yd-finish](#yd-finish)
   * [yd-application](#yd-application)
   * [yd-help](#yd-help)
   * [yd-jsonnet2json](#yd-jsonnet2json)
   * [yd-format-json](#yd-format-json)
   * [yd-version](#yd-version)
   * [yd-copy](#yd-copy-1)
   * [yd-delete / yd-rm](#yd-delete--yd-rm)
   * [yd-download](#yd-download-1)
   * [yd-ls](#yd-ls-1)
   * [yd-upload](#yd-upload-1)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Thu Jun 11 10:28:33 BST 2026 -->

<!--te-->

# Overview

This repository contains a set of command line utilities for driving the YellowDog Platform, written in Python. The scripts use the **[YellowDog Python SDK](https://docs.yellowdog.ai/sdk/python/index.html)**, the code for which can be found [on GitHub](https://github.com/yellowdog/yellowdog-sdk-python-public).

This documentation should be read in conjunction with the main **[YellowDog Documentation](https://docs.yellowdog.ai)**, which provides a comprehensive description of the concepts and operation of the YellowDog Platform.

The commands provide the following capabilities:

- **Aborting** running Tasks with the **`yd-abort`** command
- **Boosting** Allowances with the **`yd-boost`** command
- **Cancelling** Work Requirements with the **`yd-cancel`** command
- **Comparing** whether worker pools are a match for task groups with the **`yd-compare`** command
- **Creating, Updating and Removing** Compute Source Templates, Compute Requirement Templates, Keyrings, Credentials, Image Families, Allowances, Configured Worker Pools, User Attributes, Namespace Policies, Groups, and Applications with the **`yd-create`** and **`yd-remove`** commands
- **Finishing** Work Requirements with the **`yd-finish`** command
- **Following Event Streams** for Work Requirements, Worker Pools and Compute Requirements with the **`yd-follow`** command
- **Instantiating** Compute Requirements with the **`yd-instantiate`** command
- **Waiting** for Work Requirements, Worker Pools or Compute Requirements to reach a terminal state with the **`yd-wait`** command
- **Listing** YellowDog items using the **`yd-list`** command
- **Provisioning** Worker Pools with the **`yd-provision`** command
- **Resizing** Worker Pools and Compute Requirements with the **`yd-resize`** command
- **Showing** the details of any YellowDog entity using its YellowDog ID with the **`yd-show`** command
- **Showing** the details of the current Application with the **`yd-application`** command
- **Shutting Down** Worker Pools and Nodes with the **`yd-shutdown`** command
- **Submitting Node Actions** to Worker Pool nodes with the **`yd-nodeaction`** command
- **Starting** HELD Work Requirements and **Holding** (or pausing) RUNNING Work Requirements with the **`yd-start`** and **`yd-hold`** commands
- **Submitting** Work Requirements with the **`yd-submit`** command
- **Terminating** Compute Requirements with the **`yd-terminate`** command
- **Stopping**, **Starting** and **Restarting** Compute Requirements and Instances with the **`yd-compute-stop`**, **`yd-compute-start`** and **`yd-compute-restart`** commands
- **Uploading**, **Downloading**, **Deleting**, **Listing** and **Copying** files in remote data stores with the **`yd-upload`**, **`yd-download`**, **`yd-delete`**, **`yd-ls`** and **`yd-copy`** commands

The operation of the commands is controlled using TOML configuration files and/or environment variables and command line arguments. In addition, Work Requirements and Worker Pools can be defined using JSON files providing extensive configurability.

Commands are also provided for the semi-automatic setup of cloud provider accounts for use with YellowDog, and the creation of YellowDog assets to work with these cloud provider accounts. Please see **[Cloud Wizard](README_CLOUDWIZARD.md)** for more details.

Run any command with the `--help`/`-h` option to discover the command's options.

# YellowDog Prerequisites

To submit **Work Requirements** to YellowDog for processing by Configured Worker Pools (on-premise) and/or Provisioned Worker Pools (cloud-provisioned resources), you'll need:


1. A YellowDog Platform Account.


2. An Application Key & Secret: in the **Accounts** section under the **Applications** tab in the YellowDog Portal, use the **Add Application** button to create a new Application, and make a note of its **Key** and **Secret** (these will only be displayed once).

To create **Provisioned Worker Pools**, you'll need:

3. A **Keyring** created via the YellowDog Portal, with access to Cloud Provider credentials as required. The Application must be granted access to the Keyring.


4. One or more **Compute Sources** defined, and a **Compute Requirement Template** created. The images used by instances must include the YellowDog agent, configured with the Task Type(s) to match the Work Requirements to be submitted.

To set up **Configured Worker Pools**, you'll need:

5. A Configured Worker Pool Token: from the **Workers** tab in the YellowDog Portal, use the **+Add Configured Worker Pool** button to create a new Worker Pool and generate a token.


6. Obtain the YellowDog Agent and install/configure it on your on-premise systems using the Token obtained above. See guidance for [Linux](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md) and [Windows](https://github.com/yellowdog/resources/blob/main/agent-install/windows/README-CONFIGURED.md).

# Installation

Python 3.10 or later is required. If you don't have Python installed, download it from **[python.org](https://www.python.org/downloads/)**, or use your system package manager:

| Platform        | Command                             |
|-----------------|-------------------------------------|
| macOS           | `brew install python`               |
| Ubuntu / Debian | `sudo apt install python3`          |
| Windows         | `winget install Python.Python.3.12` |

Three installation methods are available. **pipx is recommended** for most users; uv is a good choice if you already use it as your Python toolchain; pip + virtual environment is the better choice if you are integrating these commands into a broader Python development workflow.

## Option 1: pipx (recommended)

**[pipx](https://pipx.pypa.io)** installs the commands into an isolated environment and puts them on your PATH automatically. You never need to create or activate a virtual environment.

### Install pipx

| Platform | Command                                                |
|----------|--------------------------------------------------------|
| macOS    | `brew install pipx && pipx ensurepath`                 |
| Linux    | `pip install --user pipx && pipx ensurepath`           |
| Windows  | `pip install --user pipx` (then restart your terminal) |

### Install the YellowDog CLI

```shell
pipx install yellowdog-cli
```

### Update

```shell
pipx upgrade yellowdog-cli
```

### With Jsonnet support

```shell
pipx install yellowdog-cli          # first-time install
pipx inject yellowdog-cli jsonnet   # add Jsonnet

pipx upgrade yellowdog-cli          # update CLI
pipx inject --force yellowdog-cli jsonnet  # update Jsonnet
```

## Option 2: uv

**[uv](https://docs.astral.sh/uv/)** is a fast, modern Python package and project manager. Like pipx, it installs CLI tools into isolated environments and puts them on your PATH automatically.

### Install uv

See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for full instructions. Quick options:

| Platform         | Command                                            |
|------------------|----------------------------------------------------|
| macOS / Linux    | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| macOS (Homebrew) | `brew install uv`                                  |
| Windows          | `winget install --id=astral-sh.uv -e`              |

### Install the YellowDog CLI

```shell
uv tool install yellowdog-cli
```

### Update

```shell
uv tool upgrade yellowdog-cli
```

### With Jsonnet support

```shell
uv tool install "yellowdog-cli[jsonnet]"
```

To update:

```shell
uv tool upgrade yellowdog-cli
```

## Option 3: pip + virtual environment

This method gives you full control over the Python environment and integrates naturally with other Python tooling.

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

> **Note:** You will need to activate the virtual environment (`source yd-env/bin/activate`) each time you open a new terminal session, or add the activation to your shell profile.

# Usage

Both installation methods add a number of **`yd-`** commands to your PATH.

Commands are run from the command line. Invoking any command with the `--help` or `-h` option will display the command line options applicable to that command, e.g.:

```text
% yd-cancel -h
usage: yd-cancel [-h] [--docs] [--config <config_file.toml>] [--key <app-key-id>] [--secret <app-key-secret>] [--url <url>] [--debug]
                 [--pac] [--no-format] [--quiet] [--env-override] [--print-pid] [--no-config] [--property <section.key=value>]
                 [--variable <var1=v1>] [--namespace [<namespace>]] [--tag [<tag>]] [--abort] [--follow] [--interactive] [--yes]
                 [--raw-events]
                 [<work-requirement-name-or-ID> ...]

YellowDog command line utility for cancelling Work Requirements

positional arguments:
  <work-requirement-name-or-ID>
                        the name(s) or YellowDog ID(s) of the work requirement(s) to be cancelled; can also supply task IDs

options:
  -h, --help            show this help message and exit
  --docs                provide a link to the documentation for this version
  --config <config_file.toml>, -c <config_file.toml>
                        configuration file in TOML format; the default to use is 'config.toml' in the current directory
  --key <app-key-id>, -k <app-key-id>
                        the application key ID
  --secret <app-key-secret>, -s <app-key-secret>
                        the application key secret
  --url <url>, -u <url>
                        the YellowDog Platform API URL (defaults to 'https://api.yellowdog.ai')
  --debug               display the Python stack trace on error
  --pac                 enable PAC (proxy auto-configuration) support
  --no-format, --nf     disable colouring and text wrapping in command output
  --quiet, -q           suppress (non-error, non-interactive) status and progress messages
  --env-override        values in '.env' file override values in the environment (also set permanently via YD_ENV_OVERRIDE)
  --print-pid, --pp     include the process ID of this CLI invocation alongside timestamp in logging messages
  --no-config, --nc     ignore the contents of any TOML configuration file (even if specified on the command line)
  --property <section.key=value>
                        override a TOML configuration property; format: 'section.key=value', e.g.
                        'workRequirement.workerTags=["mytag"]'; can be supplied multiple times
  --variable <var1=v1>, -v <var1=v1>
                        user-defined variable substitution; the option can be supplied multiple times, one per variable
  --namespace [<namespace>], -n [<namespace>]
                        the namespace to use when specifying entities; this is set to '' if the option is provided without a value
  --tag [<tag>], -t [<tag>]
                        the tag to use when naming, tagging, or selecting entities; this is set to '' if the option is provided without
                        a value
  --abort, -a           abort running tasks with immediate effect
  --follow, -f          follow progress after cancelling the work requirement(s)
  --interactive, -i     list, and interactively select, the items to act on
  --yes, -y             perform modifying/destructive actions without requiring user confirmation
  --raw-events          print the raw JSON event stream when following events
```

# Typical Workflow

A common pattern when using YellowDog is to submit a Work Requirement and provision a Worker Pool simultaneously, then follow both to completion. The `--quiet` flag returns just the YDID, making it easy to compose commands in shell scripts:

```bash
# Submit a Work Requirement and capture its YDID
WR_ID=$(yd-submit --quiet)

# Provision a Worker Pool and capture its YDID
WP_ID=$(yd-provision --quiet)

# Follow both until the Work Requirement finishes and the Worker Pool shuts down
yd-follow "$WR_ID" "$WP_ID"
```

Alternatively, `yd-submit --follow` and `yd-provision` can be run in parallel, letting the Worker Pool pick up Tasks as they are submitted:

```bash
yd-provision &
yd-submit --follow
```

When the Work Requirement is finished, the Worker Pool will scale down and shut itself down automatically based on the configured `idlePoolTimeout`.

Note that there is no fixed 1:1 relationship between Work Requirements and Worker Pools. The YellowDog Scheduler matches Task Groups to Workers based on the Task Group's run specification (worker tags, instance types, providers, regions, etc.) — any Worker Pool whose Workers satisfy those constraints is a candidate. This means a single Worker Pool can serve Task Groups from multiple Work Requirements simultaneously, and a single Work Requirement's Task Groups can be distributed across multiple Worker Pools.

# Configuration

By default, the operation of all commands is configured using a **TOML** configuration file. TOML v1.1.0 is supported, allowing multi-line tables, etc.

The configuration file has four possible sections:

1. A `common` section that contains required security properties for interacting with the YellowDog platform, sets the Namespace in which YellowDog assets and objects are created, and a Tag that is used for tagging and naming assets and objects.
2. A `workRequirement` section that defines the properties of Work Requirements to be submitted to the YellowDog platform.
3. A `workerPool` section that defines the properties of Provisioned Worker Pools to be created using the YellowDog platform. (This can be substituted by a `computeRequirement` section if instance provisioning is all that's required.)
4. A `dataClient` section that configures the remote data store used by the `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy` commands.

There is a documented template TOML file provided in [config-template.toml](config-template.toml), containing the main properties that can be configured.

The name of the configuration file can be supplied in two different ways:

1. On the command line, using the `--config` or `-c` options, e.g.:<br>`yd-submit -c jobs/config_1.toml`
2. If not supplied, the commands look for a `config.toml` file in the current directory

(The `YD_CONF` environment variable is no longer supported for selecting the configuration file; commands will exit with an error if it is set.)

# Naming Rules

All entity names used within the YellowDog Platform must comply with the following rules:

- Names can only contain the following: lowercase letters, digits, hyphens and underscores (note that spaces are not permitted)
- Names must start with a letter
- Names must end with a letter or digit
- Name length must 60 characters or fewer

These restrictions apply to entities including Namespaces, Tags, Work Requirements, Task Groups, Tasks, Worker Pools, and Compute Requirements, and also apply to entities that are currently used indirectly by these scripts, including Usernames, Credentials, Keyrings, Compute Sources and Compute Templates.

Later sections of this document describe variable substitutions implemented with user-defined and CSV-file-defined variables. As a type modifier within these substitution expressions, the `format_name:` option is available, and works in the same manner as `num:`, `bool:`, etc. The `format_name:` modifier will convert the substituted string into one that satisfies YellowDog naming, by switching characters to lower case, etc.

For example, a variable substitution `{{format_name:ligand_name}}`, with variable `ligand_name` set to `DCCCDE_00000s`, would substitute to become `dcccde_00000s`, and would be acceptable for use as a component of a YellowDog name.

# Common Properties

The `[common]` section of the configuration file can contain the following properties:

| Property    | Description                                                                                 |
|:------------|:--------------------------------------------------------------------------------------------|
| `key`       | The **key ID** of the YellowDog Application under which the commands will run               |
| `secret`    | The **key secret** of the YellowDog Application under which the commands will run           |
| `namespace` | The **namespace** to be used for grouping resources                                         |
| `tag`       | The **tag** to be used for tagging resources and naming objects                             |
| `url`       | The **URL** of the YellowDog Platform API endpoint. Defaults to `https://api.yellowdog.ai`. |
| `usePAC`    | Use PAC (proxy autoconfiguration) if set to `true`                                          |
| `variables` | A table containing **variable substitutions** (see the Variables section below)             |
| `certificates` | The path of a **CA certificates bundle** to use for HTTPS requests (sets the `REQUESTS_CA_BUNDLE` environment variable) |

An example `common` section is shown below:

```toml
[common]
    key = "asdfghjklzxcvb-1234567"
    secret = "qwertyuiopasdfghjklzxcvbnm1234567890qwertyu"
    namespace = "project-x"
    tag = "testing-{{username}}"
```

Indentation is optional in TOML files and is for readability only.

## Importing `common` Properties

The `common` section can import properties from a separate TOML file, using the `importCommon` property. For example, the `key` and `secret` might be in a shared TOML file called `app_credentials.toml`, with the following contents:

```toml
[common]
    key = "asdfghjklzxcvb-1234567"
    secret = "qwertyuiopasdfghjklzxcvbnm1234567890qwertyu"
```

This could be imported into the main configuration as follows:

```toml
[common]
    importCommon = "app_credentials.toml"

    namespace = "project-x"
    tag = "testing-{{username}}"
```

Properties set in the imported file are superseded by any of the same properties that are present in the main configuration file.

## HTTPS Proxy Support

The commands will respect the value of the environment variable `HTTPS_PROXY` if routing through a proxy is required.

In addition, commands can use proxy autoconfiguration (PAC) if the `--pac` command line option is specified, or if the `usePAC` property is set to `true` in the `[common]` section of the `config.toml` file.

## Specifying Common Properties using the Command Line or Environment Variables

All the common properties can be set using command line options, or in environment variables.

The **command line options** are as follows:

- `--key` or `-k`
- `--secret` or `-s`
- `--namespace` or `-n`
- `--tag` or `-t`
- `--url` or `-u`
- `--pac`

These options can also be listed by running a command with the `--help` or `-h` option.

The **environment variables** are as follows:

- `YD_KEY` (or `YD_API_KEY_ID`)
- `YD_SECRET` (or `YD_API_KEY_SECRET`)
- `YD_URL` (or `YD_API_URL`)
- `YD_NAMESPACE`
- `YD_TAG`

When setting the value of the above properties, a property set on the command line takes precedence over one set via an environment variable, and both take precedence over a value set in the configuration file.

**Exception**: if the configuration file is explicitly selected using the `--config`/`-c` option, its contents take precedence over environment variables (but not over properties set on the command line). This makes it easy to direct a command at a specific configuration without first having to unset environment variables.

If all the required common properties are set using the command line or environment variables, then the entire `common` section of the TOML file can be omitted.

In addition, setting the `YD_YES` environment variable (to any non-empty value) suppresses user confirmation prompts for all commands, equivalent to supplying `--yes`/`-y` on every invocation.

## Overriding Arbitrary TOML Properties on the Command Line

Any property in the TOML configuration file can be overridden on the command line using the `--property` flag (repeatable):

```
--property 'section.key=value'
```

The `section` must be one of `common`, `dataClient`, `workRequirement`, `workerPool`, or `computeRequirement`. The `value` is interpreted as JSON first (so booleans, numbers, lists, and dicts are handled correctly), falling back to a plain string if JSON parsing fails.

Examples:

```bash
# Override a single string value
yd-submit --property 'common.namespace=myproject'

# Override a numeric value
yd-provision --property 'workerPool.targetInstanceCount=4'

# Override a list
yd-submit --property 'workRequirement.workerTags=["gpu","large"]'

# Override a boolean
yd-provision --property 'workerPool.maintainInstanceCount=true'

# Multiple overrides
yd-submit --property 'workRequirement.maxRetries=3' \
          --property 'workRequirement.priority=1.5'
```

`--property` overrides are applied after the TOML file is loaded, so they take effect regardless of what the file contains. Specific CLI flags (`--namespace`, `--tag`, etc.) are still applied on top, as before. `{{variable}}` substitutions within values are resolved in the normal way.

Use `--dry-run` to verify the effect of an override before submitting:

```bash
yd-submit --property 'workRequirement.priority=2.0' --dry-run --quiet
```

## Support for `.env` Files

Environment variables can also be set in a `.env` file.

The `.env` file is located by checking the following locations in order:

1. The directory containing the active `config.toml` file (as specified by `--config`, or the default `config.toml` in the current directory). This allows a `.env` file to live alongside its `config.toml` and be found even when commands are run from a different directory.
2. Searching upward from the current working directory (standard `python-dotenv` behaviour).

Entries in the `.env` file will not overwrite existing environment variables — i.e., environment variables take precedence over entries in the `.env` file. This precedence can be reversed by using the `--env-override` command line option, or by setting the `YD_ENV_OVERRIDE` environment variable (e.g., in `.bashrc`/`.zshrc`) to make `.env` values always take precedence.

Environment variables sourced from a `.env` file whose names start with `YD` will be reported on the command line. Variables whose names do not start with `YD` will not be reported, but they will still be applied.

## Variable Substitutions in Common Properties

Note the use of `{{username}}` in the value of the `tag` property example above: this is a **variable substitution** that can optionally be used to insert the login username of the user running the commands. So, for username `abc`, the `tag` would be set to `testing-abc`. This can be helpful to disambiguate multiple users running with the same configuration data.

Variable substitutions are discussed in more detail below.

# Variable Substitutions

Variable substitutions provide a powerful mechanism for introducing variable values into TOML configuration files, and JSON/Jsonnet definitions. They can be included in the value of any property in any of these objects, including in values within arrays (lists), e.g., for the `arguments` property, and tables (dictionaries), e.g., the `environment` property.

Variable substitutions are expressed using the `{{variable}}` notation (note: no spaces between the double brackets and the variable name), where the expression is replaced by the value of `variable`.

Substitutions can also be performed for non-string (number, boolean, array, and table) values using the `num:`, `bool:`, `array:`, and `table:` prefixes within the variable substitution:

- Define the variable substitution using one of the following patterns: `"{{num:my_int}}"`, `"{{num:my_float}}"`, `"{{bool:my_bool}}"`, `"{{array:my_array}}"`, `"{{table:my_table}}"`
- Variable definitions supplied on the command line would then be of the form, e.g.: 

```shell
 yd-submit -v my_int=5 -v my_float=2.5 -v my_bool=true \
           -v my_array="[1,2,3]" -v my_table='{"A": 100, "B": 200}'
```

- In the processed JSON (or TOML), these values would become `5`, `2.5`, `true`, `[1,2,3]`, and `{"A": 100, "B": 200}`, respectively, converted from strings to their correct JSON types

> **Note:** `array:` and `table:` values must be valid JSON. Use double-quoted strings, and `true`/`false`/`null` for booleans and null values.

## Default Variables

The following substitutions are automatically created and can be used in any section of the configuration file, or in any JSON specification:

| Directive             | Description                                                    | Example of Substitution |
|:----------------------|:---------------------------------------------------------------|:------------------------|
| `{{username}}`        | The current user's login username, lower case, spaces replaced | jane_smith              |
| `{{date}}`            | The current date (UTC): YYMMDD                                 | 221027                  |
| `{{time}}`            | The current time (UTC): HHMMSSss                               | 16302699                |
| `{{datetime}}`        | Concatenation of the date and time, with a '-' separator       | 221027-163026           |
| `{{random}}`          | A random, three digit hexadecimal number (lower case)          | a1c                     |
| `{{namespace}}`       | The `namespace` property.                                      | my_namespace            |
| `{{tag}}`             | The `tag` property.                                            | my_tag                  |
| `{{key}}`             | The application `key` property.                                |                         |
| `{{secret}}`          | The application `secret` property.                             |                         |
| `{{url}}`             | The Platform `url` property.                                   |                         |
| `{{config_dir_abs}}`  | The absolute directory path of the configuration file          | /yellowdog/workloads    |
| `{{config_dir_name}}` | The immediate containing directory of the configuration file   | workloads               |

For the `date`, `time`, `datetime` and `random` directives, the same values will be used for the duration of a command -- i.e., if `{{time}}` is used within multiple properties, the identical value will be used for each substitution.

The `config_dir_` substitutions use the name of the directory containing the nominated TOML configuration file, or the invocation directory if no configuration file is supplied.

## User-Defined Variables

User-defined variables can be supplied using an option on the command line, by setting environment variables prefixed with `YD_VAR_`, by using general environment variables, or by including properties in the `[common]` section of the TOML configuration file.

### Variable Naming

User-defined variable names must not start with a reserved prefix. The implementation does not enforce any other restrictions on characters (including spaces), but by convention names should be simple identifiers without spaces. When enclosing a variable name in curly brackets, don't insert spaces between the variable name and the brackets.

**Reserved prefixes** — the following prefixes have special meaning and must not be used as the start of a variable name:

| Prefix         | Purpose                                          |
|----------------|--------------------------------------------------|
| `num:`         | Type tag: interpret value as a number            |
| `bool:`        | Type tag: interpret value as a boolean           |
| `array:`       | Type tag: interpret value as an array            |
| `table:`       | Type tag: interpret value as a table (dict)      |
| `format_name:` | Type tag: convert value to a YellowDog-safe name |
| `env:`         | Look up a general environment variable           |

**Other constraints:**

- Variable names cannot contain `}}` (closing delimiter), `:=` (default-value separator), or `::` (unset suffix), as these are parsed as syntax.
- `YD_VAR_` environment variables create variable names with the **exact case** of the suffix — `YD_VAR_SUFFIX` creates `SUFFIX`, not `suffix`. On Windows, environment variable names are uppercased by the OS, so use uppercase names only.
- When defining variables in `[common.variables]` in TOML, names follow TOML bare-key rules (`a-z`, `A-Z`, `0-9`, `-`, `_`) unless quoted.

### Setting Variable Values

1. The **command line** option is `--variable` (or `-v`). For example, `yd-submit -v project_code=pr-213-a -v run_id=1234` will establish two new variables that can be used as `{{project_code}}` and `{{run_id}}`, which will be substituted by `pr-213-a` and `1234` respectively.


2. For **environment variables**, setting the variable `YD_VAR_project_code="pr-213-a"` will create a new variable that can be accessed as `{{project_code}}`, which will be substituted by `pr-213-a`. Note that if running on Windows, all environment variable names are case-insensitive and converted to upper case, so choose upper case variable names only.


3. **General (i.e., non-`YD_VAR_`) environment variables** can be used by adding the `env:` prefix before the name of the environment variable in the substitution, e.g.: `{{env:ENV_VAR_NAME}}`. (If you also need to use one of the type prefixes, just do so as follows (e.g.): `{{num:env:COUNT}}`). A default value can also be provided for the case where the environment variable is not set: `{{env:ENV_VAR_NAME:=default_value}}`.


4. For **setting within the TOML file**, include a **`variables`** table in the `[common]` section of the file. E.g., `variables = {project_code = "pr-213a", run_id = "1234"}`. Note that this can also use the form:

```toml
[common.variables]
    project_code = "pr-213a"
    run_id = "1234"
```

### Precedence Order

The precedence order for setting variables is:

1. Command line (`--variable`/`-v`)
2. `YD_VAR_` environment variables
3. `YD_VAR_` variables defined in a `.env` file
4. TOML configuration file (`[common.variables]`)

**Exception**: if the configuration file is explicitly selected using the `--config`/`-c` option, its `[common.variables]` definitions take precedence over `YD_VAR_` environment variables (items 2 and 3), but never over variables set on the command line.

(Substitutions using the `{{env:NAME}}` syntax are resolved directly from the named environment variable at the point of use, and do not participate in this precedence order.)

This method can also be used to override some default variables, e.g., setting `-v username="other-user"` will override the default `{{username}}` variable.

### Nested Variables

In the case of **TOML file properties only**, variable substitutions can be nested.

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

Nesting can be up to three levels deep including the top level. Note that sequencing of properties in the TOML file does not matter, e.g., variable `{{a}}` can depend on a variable `{{b}}` that is defined after it in the file.

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

Default values can be used anywhere that variable substitutions are allowed.  In TOML files only, nested variable substitutions can be used inside default values, e.g.:

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
tag           = "{{tag::}}"          # removed if 'tag' is not set
maxRetries    = "{{num:retries::}}"  # removed if 'retries' is not set
```

If `tag` is not supplied, the `tag` property will be absent from the submitted Work Requirement (rather than being set to an empty string or causing an error). If `tag` is supplied, e.g. via `-v tag=my-tag`, it will be used as the value.

This also works inside JSON/Jsonnet specifications and for list elements.

The `env:` prefix can be combined with the unset suffix to make a property conditional on an environment variable being set:

```toml
region = "{{env:MY_REGION::}}"   # removed if MY_REGION is not set
```

The bare `{{::}}` (no variable name) always removes the property unconditionally — useful for explicitly suppressing a property that a base template includes:

```toml
taskType = "{{::}}"   # always removed
```

## Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data

In JSON/Jsonnet specifications for Worker Pools and Compute Requirements, variable substitutions **must be prefixed and postfixed by double underscores** `__`, e.g., `__{{username}}__`. This is to disambiguate client-side variable substitutions from server-side Mustache variable processing.

Variable substitutions can also be used within **User Data** to be supplied to instances, for which the same prefix/postfix requirement applies, **including** for User Data supplied directly using the `userData` property in the `workerPool` section of the TOML file.

The same prefix/postfix requirement applies to the content of files referenced by the `contentFile` and `contentFiles` properties in `writeFile` Node Actions — see [Node Actions](#node-actions).

# Work Requirements

A **Work Requirement** is the top-level unit of work submitted to the YellowDog platform. It contains one or more **Task Groups**, each of which contains one or more **Tasks**. Work Requirements are created and submitted using the **`yd-submit`** command, and can be updated after submission — adding Task Groups or Tasks — using the `--add-to` option.

The `workRequirement` section of the configuration file is optional. It's used only by the `yd-submit` command, and controls the Work Requirement that is submitted to the Platform.

**Jump to:** [Property Dictionary](#work-requirement-property-dictionary) · [Task Templates](#task-templates) · [Automatic Properties](#automatic-properties) · [Examples](#examples) · [Variable Substitutions](#variable-substitutions-in-work-requirement-properties) · [Dry-Running](#dry-running-work-requirement-submissions) · [Data Client](#using-the-yellowdog-data-client) · [Task Execution Context](#task-execution-context) · [CSV Data](#specifying-work-requirements-using-csv-data)

The details of a Work Requirement to be submitted can be captured entirely within the TOML configuration file for simple (single Task Group) examples. More complex examples capture the Work Requirement in a combination of the TOML file plus a JSON document, or in a JSON document only.

## Work Requirement JSON File Structure

Work Requirements are represented in JSON documents using a containment hierarchy of a **Work Requirement** containing a **list of Task Groups**, containing a **list of Tasks**.

A very simple example document is shown below with a top-level Work Requirement containing two Task Groups each containing two Tasks, each with a different set of arguments to be passed to the Task.

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": [1, 2, 3]
        },
        {
          "arguments": [4, 5, 6]
        }
      ]
    },
    {
      "tasks": [
        {
          "arguments": [7, 8, 9]
        },
        {
          "arguments": [10, 11, 12]
        }
      ]
    }
  ]
}

```

To specify the file containing the JSON document, either populate the `workRequirementData` property in the `workRequirement` section of the TOML configuration file with the JSON filename, or specify it on the command line as a positional argument (which will override the property in the TOML file), e.g.

`yd-submit --config myconfig.toml my_workreq.json`

## Property Inheritance

Work Requirement specifications can be simplified substantially by the property inheritance features in `yd-submit`. In general, properties that are set at a higher level in the hierarchy are inherited at lower levels, unless explicitly overridden.

This means that a property set in the `workRequirement` section of the TOML file can be inherited successively by the Work Requirement, Task Groups, and Tasks in the JSON document (assuming the property is available at each level).  Hence, Tasks inherit from Task Groups, which inherit from the Work Requirement in the JSON document, which inherits from the `workRequirement` properties in the TOML file.

Overridden properties are also inherited at lower levels in the hierarchy. E.g., if a property is set at the Task Group level, it will be inherited by the Tasks in that Task Group unless explicitly overridden.

## Work Requirement Property Dictionary

The following table outlines all the properties available for defining Work Requirements, and the levels at which they are allowed to be used. So, for example, the `provider` property can be set in the TOML file, at the Work Requirement Level or at the Task Group Level, but not at the Task level, and property `dependentOn` can only be set at the Task Group level.


| Property Name               | Description                                                                                                                                                                                                                         | TOML | WR  | TGrp | Task |
|:----------------------------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|:-----|:----|:-----|:-----|
| `addEnvironment`            | A table of environment variable key-value pairs merged into each Task's `environment`. Keys in `addEnvironment` override any matching keys already present in `environment`. E.g., `{EXTRA = "val", X = "1"}`.                      | Yes  | Yes | Yes  |      |
| `addYDEnvironment`          | Automatically add YellowDog environment variables to each Task's environment.                                                                                                                                                       | Yes  | Yes | Yes  | Yes  |
| `arguments`                 | The list of arguments to be passed to the Task when it is executed. E.g.: `[1, "Two"]`.                                                                                                                                             | Yes  | Yes | Yes  | Yes  |
| `argumentsPostfix`          | A fixed list of arguments appended after `arguments` for every Task. Combined result is `argumentsPrefix` + `arguments` + `argumentsPostfix`. E.g.: `["--output", "results/"]`.                                                     | Yes  | Yes | Yes  |      |
| `argumentsPrefix`           | A fixed list of arguments prepended before `arguments` for every Task. Combined result is `argumentsPrefix` + `arguments` + `argumentsPostfix`. E.g.: `["--input", "data/"]`.                                                       | Yes  | Yes | Yes  |      |
| `completedTaskTtl`          | The time (in minutes) to live for completed Tasks. If set, Tasks that have been completed for longer than this period will be deleted. E.g.: `10.0`.                                                                                | Yes  | Yes | Yes  |      |
| `csvFile`                   | The name of the CSV file used to derive Task data. An alternative to `csvFiles` that can be used when there's only a single CSV file. E.g. `"file.csv"`.                                                                            | Yes  |     |      |      |
| `csvFiles`                  | A list of CSV files used to derive Task data. E.g. `["file.csv", "file_2.csv:2]`.                                                                                                                                                   | Yes  |     |      |      |
| `dependencies`              | The names of other Task Groups within the same Work Requirement that must be successfully completed before the Task Group is started. E.g. `["task_group_1", "task_group_2"]`.                                                      |      |     | Yes  |      |
| `dependentOn`               | **Deprecated** — use `dependencies` instead (see above). Takes a single string rather than a list. Support for `dependentOn` will be removed in a future release.                                                                   |      |     | Yes  |      |
| `disablePreallocation`      | If `true`, tasks are only allocated to nodes as workers become idle and are not queued on the node. Default: `false`.                                                                                                               | Yes  | Yes | Yes  |      |
| `environment`               | The environment variables to set for a Task when it's executed. E.g., JSON: `{"VAR_1": "abc", "VAR_2": "def"}`, TOML: `{VAR_1 = "abc", VAR_2 = "def"}`.                                                                             | Yes  | Yes | Yes  | Yes  |
| `finishIfAllTasksFinished`  | If true, the Task Group will finish automatically if all contained tasks finish. Default:`true`.                                                                                                                                    | Yes  | Yes | Yes  |      |
| `finishIfAnyTaskFailed`     | If true, the Task Group will be failed automatically if any contained tasks fail. Default:`false`.                                                                                                                                  | Yes  | Yes | Yes  |      |
| `instancePricingPreference` | The preferred instance pricing type for Tasks. One of: `SPOT_ONLY`, `ON_DEMAND_ONLY`, `SPOT_THEN_ON_DEMAND`, `ON_DEMAND_THEN_SPOT`. Default: no preference.                                                                         | Yes  | Yes | Yes  |      |
| `instanceTypes`             | The machine instance types that can be used to execute Tasks. E.g., `["t3.micro", "t3a.micro"]`.                                                                                                                                    | Yes  | Yes | Yes  |      |
| `failurePolicy`             | A policy for resubmitting a Task to a different Task Group when it would otherwise be `FAILED`. See [Task Retries and Failure Policies](#task-retries-and-failure-policies).                                                       | Yes  | Yes | Yes  |      |
| `maximumTaskRetries`        | (Deprecated — see `retryPolicy`.) The maximum number of times a Task can be retried after it has failed. E.g.: `5`.                                                                                                                  | Yes  | Yes | Yes  |      |
| `maxWorkers`                | The maximum number of Workers that can be claimed for the associated Task Group. E.g., `10`.                                                                                                                                        | Yes  | Yes | Yes  |      |
| `minWorkers`                | The minimum number of Workers that the associated Task Group will retain even if this exceeds the current number of Tasks. E.g., `1`.                                                                                               | Yes  | Yes | Yes  |      |
| `name`                      | The name of the Work Requirement, Task Group or Task. E.g., `"wr_name"`. Note that the `name` property is not inherited.                                                                                                            | Yes  | Yes | Yes  | Yes  |
| `namespaces`                | Only Workers whose Worker Pools match one of the namespaces in this list can be claimed by the Task Group. E.g., `["namespace_1", "namespace_2"]. Defaults to `None`.                                                               | Yes  | Yes | Yes  |      |
| `parallelBatches`           | The number of parallel threads to use when uploading batches of Tasks.                                                                                                                                                              | Yes  |     |      |      |
| `priority`                  | The priority of Work Requirements and Task Groups. Higher priority acquires Workers ahead of lower priority. E.g., `0.0`.                                                                                                           | Yes  | Yes | Yes  |      |
| `providers`                 | Constrains the YellowDog Scheduler only to execute tasks from the associated Task Group on the specified providers. E.g., `["AWS", "GOOGLE"]`.                                                                                      | Yes  | Yes | Yes  |      |
| `ram`                       | Range constraint on GB of RAM that are required to execute Tasks. E.g., `[2.5, 4.0]`. Either bound may be left unset for a one-sided limit, e.g. `[2.5, null]` (no upper limit) or `[null, 4.0]` (no lower limit); in TOML use the string `"none"` or `"null"` instead of `null`.                           | Yes  | Yes | Yes  |      |
| `regions`                   | Constrains the YellowDog Scheduler only to execute Tasks from the associated Task Group in the specified regions. E.g., `["eu-west-2]`.                                                                                             | Yes  | Yes | Yes  |      |
| `retryPolicy`               | A policy controlling Task retries on error. See [Task Retries and Failure Policies](#task-retries-and-failure-policies).                                                                                                            | Yes  | Yes | Yes  |      |
| `retryableErrors`           | (Deprecated — see `retryPolicy`.) A list of error condition combinations under which Tasks will be retried (up to `maximumTaskRetries`). Retries will always be attempted if the list is empty (the default). See the TOML/JSON section for examples.                 | Yes  | Yes | Yes  |      |
| `setTaskNames`              | Set this to `false` to suppress automatic generation of Task names. Defaults to `true`. Task names that are set by the user will still be observed. Note that Task names must be set if any outputs are specified.                  | Yes  | Yes | Yes  | Yes  |
| `tag`                       | A tag that can be associated with a Work Requirement, Task Group or Task. Note there is **no property inheritance** for these tags.                                                                                                 | Yes  | Yes | Yes  | Yes  |
| `taskBatchSize`             | Determines the batch size used to add Tasks to Task Groups. Default is 1,000.                                                                                                                                                       | Yes  |     |      |      |
| `taskCount`                 | The number of times to execute the Task.                                                                                                                                                                                            | Yes  | Yes | Yes  |      |
| `taskData`                  | The data to be passed to the Worker when the Task is started. E.g., `"mydata"`. Becomes file `taskdata.txt` in the Task's working directory when the task executes.                                                                 | Yes  | Yes | Yes  | Yes  |
| `taskDataFile`              | Populate the `taskData` property above with the contents of the specified file. E.g., `"my_task_data_file.txt"`.                                                                                                                    | Yes  | Yes | Yes  | Yes  |
| `taskDataFiles`             | Populate the `taskData` property above by concatenating the contents of a list of files. Mutually exclusive with `taskData` and `taskDataFile`. E.g., `["header.txt", "body.txt"]`.                                                | Yes  | Yes | Yes  | Yes  |
| `taskDataInputs`            | A list of data inputs to be downloaded by the task E.g., JSON: `{"source": "src", "destination": "dest"}`, TOML: `{source = "src", destination = "dest"}`.                                                                          | Yes  | Yes | Yes  | Yes  |
| `taskDataOutputs`           | A list of data outputs to be uploaded at the conclusion of a task E.g., JSON: `{"source": "src", "destination": "dest", "alwaysUpload": true}`, TOML: `{source = "src", destination = "dest", alwaysUpload = true}`.                | Yes  | Yes | Yes  | Yes  |
| `taskName`                  | The name to use for the Task. Only usable in the TOML file. Mostly useful in conjunction with CSV Task data. E.g., `"my_task_number_{{task_number}}"`.                                                                              | Yes  |     |      |      |
| `taskGroupCount`            | Create `taskGroupCount` duplicates of a single Task Group.                                                                                                                                                                          | Yes  | Yes |      |      |
| `taskGroupName`             | The name to use for the Task Group. Only usable in the TOML file. E.g., `"my_tg_number_{{task_group_number}}"`.                                                                                                                     | Yes  |     |      |      |
| `taskTemplate`              | Sets default `taskType`, `taskData` (or `taskDataFile`/`taskDataFiles`), and/or `environment` for all Tasks in a Task Group; applied by the platform, allowing Tasks to be more compact. E.g., `{"taskType": "docker", "environment": {"X": "1"}}`. | Yes  | Yes | Yes  |      |
| `taskTimeout`               | The timeout in minutes after which an executing Task will be terminated and reported as `FAILED`. E.g. `120.0`. The default is no timeout.                                                                                          | Yes  | Yes | Yes  |      |
| `timeout`                   | As above, but set at the individual Task level, which overrides the group level `taskTimeout` property (if present).                                                                                                                | Yes  |     |      | Yes  |
| `taskType`                  | The Task Type of a Task. E.g., `"docker"`.                                                                                                                                                                                          | Yes  |     |      | Yes  |
| `taskTypes`                 | The list of Task Types required by the range of Tasks in a Task Group. E.g., `["docker", "bash"]`. If omitted, the value is auto-derived from the `taskType` of the constituent Tasks (see [Automatic `taskTypes` Population](#automatic-tasktypes-population) below).             |      | Yes | Yes  |      |
| `tasksPerWorker`            | Determines the number of Worker claims based on splitting the number of unfinished Tasks across Workers. E.g., `1`.                                                                                                                 | Yes  | Yes | Yes  |      |
| `vcpus`                     | Range constraint on number of vCPUs that are required to execute Tasks E.g., `[2.0, 4.0]`. Either bound may be left unset for a one-sided limit, e.g. `[2.0, null]` (no upper limit) or `[null, 4.0]` (no lower limit); in TOML use the string `"none"` or `"null"` instead of `null`.                      | Yes  | Yes | Yes  |      |
| `workerTags`                | The list of Worker Tags that will be used to match against the Worker Tag of a candidate Worker. E.g., `["tag_x", "tag_y"]`.                                                                                                        | Yes  | Yes | Yes  |      |
| `workRequirementData`       | The name of the file containing the JSON document in which the Work Requirement is defined. E.g., `"test_workreq.json"`.                                                                                                            | Yes  |     |      |      |

## Automatic `taskTypes` Population

A Task Group's `taskTypes` list (which determines which Workers can pick up Tasks in the group) can be omitted: it will be populated from the `taskType` of the constituent Tasks. When both are supplied, the resulting list is the **union** of the explicit `taskTypes` and every `taskType` set on the Tasks in the group.

For example, this Task Group has no explicit `taskTypes` — the group's allowlist becomes `["bash"]` automatically:

```json
{
  "name": "my-tasks",
  "tasks": [
    {"name": "task-1", "taskType": "bash", "arguments": ["echo", "hello"]},
    {"name": "task-2", "taskType": "bash", "arguments": ["echo", "world"]}
  ]
}
```

And in this example, the group's allowlist becomes `["bash", "docker"]` (the union):

```json
{
  "name": "mixed-tasks",
  "taskTypes": ["bash"],
  "tasks": [
    {"name": "shell-task", "taskType": "bash", "arguments": ["echo", "hi"]},
    {"name": "container-task", "taskType": "docker", "taskData": "..."}
  ]
}
```

If `taskTypes` is still empty after this union, the CLI falls back (in order) to the `[workRequirement] taskType` config property and to `taskTemplate.taskType`. If none of these provide a value and the Task Group contains Tasks, submission fails with a clear error.

When using `yd-submit --add-to <wr>` to add Tasks to an **existing** Task Group, the existing group's `taskTypes` allowlist cannot be modified (the platform does not support mutating `taskTypes` after the Task Group is created). The CLI detects this case before submitting anything and fails with a clear error if the incoming Tasks introduce a `taskType` that the existing group does not already allow. The remedy is to use a different Task Group name (so a new Task Group is created with the union of `taskTypes`) or change the offending Tasks to use a supported `taskType`.

## Task Retries and Failure Policies

A Task Group's `runSpecification` can carry one **`retryPolicy`** and one **`failurePolicy`**. The retry policy is evaluated after each errored attempt; if retries are exhausted (or excluded by the policy), the failure policy can re-issue the Task in a different Task Group rather than letting it terminate as `FAILED`.

### Selecting errors (`Selection<TaskErrorSelector>`)

Both policies select Tasks by their most-recent `TaskError` using a **`Selection`** of one or more `TaskErrorSelector` entries. Every `Selection` in the spec is a dict of the form:

```json
{
  "includes": [ ... ],
  "excludes": [ ... ]
}
```

Either `includes` or `excludes` (or both) must be present. A Task matches the selection if at least one entry under `includes` matches **and** no entry under `excludes` matches. Bare lists are rejected — wrap them as `{"includes": [...]}` to be explicit.

Each `TaskErrorSelector` has three optional fields, each itself a Selection of primitive values; an entry matches a Task error when **every** specified field's Selection matches (AND logic across the fields):

| Field               | Selection of      | Description                                                                                                |
|:--------------------|:------------------|:-----------------------------------------------------------------------------------------------------------|
| `errorTypes`        | strings           | Task error types — e.g. `"ALLOCATION_LOST"`, `"PROCESS_NON_ZERO_EXIT"`, `"TIMED_OUT"`.                     |
| `statusesAtFailure` | TaskStatus names  | Task status at the time of the error — e.g. `"FAILED"`.                                                    |
| `processExitCodes`  | integers          | The Task process exit code — e.g. `137` (OOM), `143` (SIGTERM). Implies `errorType = PROCESS_NON_ZERO_EXIT`. |

### `retryPolicy`

```json
{
  "retryPolicy": {
    "maxRetries": 3,
    "retryErrors": {
      "includes": [
        {"errorTypes": {"includes": ["ALLOCATION_LOST"]}},
        {"processExitCodes": {"includes": [143]}}
      ]
    }
  }
}
```

`maxRetries` is required and must be `>= 0` (set it to `0` to define the policy but disable retries). `retryErrors` is optional — when omitted, all Task errors are eligible for retry.

### `failurePolicy`

When retries are exhausted (or the error didn't match `retryPolicy.retryErrors`), a `failurePolicy` can resubmit the Task in another Task Group within the same Work Requirement:

```json
{
  "failurePolicy": {
    "resubmissionDestinations": [
      {
        "destinationTaskGroup": "on-demand-tg",
        "resubmitErrors": {
          "includes": [{"errorTypes": {"includes": ["ALLOCATION_LOST"]}}]
        }
      },
      {
        "destinationTaskGroup": "high-memory-tg",
        "resubmitErrors": {
          "includes": [{"processExitCodes": {"includes": [137]}}]
        }
      }
    ]
  }
}
```

Destinations are evaluated **in order**; the first matching entry wins. A resubmitted Task becomes `RESUBMITTED` (a terminal status), and a copy is added to the destination Task Group with its `resubmittedFromTaskId` linking back to the original. The original Task carries `resubmittedToTaskId` pointing forward.

Common use cases:

- **Spot → on-demand fallback**: retry preemptions a few times in a spot-priced Task Group, then resubmit to an on-demand Task Group.
- **Out-of-memory → larger instance**: exit code 137 in a default-sized group resubmits to a Task Group with more `ram` or `vcpus`.

### Deprecated: `maximumTaskRetries` / `retryableErrors`

The legacy retry mechanism is still accepted but **cannot be combined with `retryPolicy`** on the same Task Group — `yd-submit` will reject the spec with a clear error, because both control how many times and on which errors a Task is retried. Using the legacy fields emits a one-time deprecation warning per invocation.

`failurePolicy` *can* be used alongside `maximumTaskRetries` / `retryableErrors`: the legacy retry mechanism runs first, and if retries are exhausted, the `failurePolicy` is consulted for resubmission. This lets you adopt failure-based resubmission without simultaneously migrating your existing retry configuration.

#### Migration

The minimal replacement for `maximumTaskRetries = N` (with no error filtering) is a `retryPolicy` with only `maxRetries` set — every error is eligible for retry, matching the legacy behaviour.

**TOML** — under `[workRequirement]`:

```toml
# Before (deprecated)
[workRequirement]
    maximumTaskRetries = 3

# After (equivalent — retries on any error)
[workRequirement]
    retryPolicy.maxRetries = 3

# After (with error filtering)
[workRequirement.retryPolicy]
    maxRetries = 3
    retryErrors.includes = [
        { errorTypes = { includes = ["ALLOCATION_LOST"] } },
        { processExitCodes = { includes = [143] } },
    ]
```

**JSON / Jsonnet** — inside a Task Group:

```json
{
  "retryPolicy": {
    "maxRetries": 3,
    "retryErrors": {
      "includes": [
        {"errorTypes": {"includes": ["ALLOCATION_LOST"]}},
        {"processExitCodes": {"includes": [143]}}
      ]
    }
  }
}
```

A legacy `retryableErrors` entry's three fields (`errorTypes`, `statusesAtFailure`, `processExitCodes`) all migrate to the corresponding fields on a `TaskErrorSelector`, with each wrapped in a `{"includes": [...]}` Selection. Legacy semantics — a Task retried if **any** entry matched — translate to a single `includes` list of `TaskErrorSelector` entries.

### Caveat — agent version

The retry/failure selection by `errorTypes`/`processExitCodes` depends on the YellowDog Agent recording which error caused the Task to fail. Older Agent versions don't populate that field, so Selection precision is reduced when running against older Workers — `maxRetries` and unconditional resubmission still work, but error-typed selectors won't match precisely. Upgrade Workers to the current Agent release for full behaviour.

## Merging Additional Environment Variables into Tasks

The `addEnvironment` property allows a fixed set of environment variable key-value pairs to be merged into the `environment` of every Task, without replacing the entire `environment` property. Any key in `addEnvironment` that also exists in the Task's `environment` is **overridden** by the value from `addEnvironment`.

`addEnvironment` follows the same inheritance hierarchy as `argumentsPrefix` and `argumentsPostfix`: it can be set in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level (not at the per-Task level), with lower levels taking precedence.

### Example — TOML

```toml
[workRequirement]
    environment = {MY_VAR = "original", KEEP = "kept"}
    addEnvironment = {MY_VAR = "overridden", EXTRA = "new"}
    # Effective environment for each task: {MY_VAR = "overridden", KEEP = "kept", EXTRA = "new"}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "environment": {"MY_VAR": "original", "KEEP": "kept"},
      "addEnvironment": {"MY_VAR": "overridden", "EXTRA": "new"},
      "tasks": [{}]
    }
  ]
}
```

## Argument Prefix and Postfix

The `argumentsPrefix` and `argumentsPostfix` properties allow a fixed list of arguments to be prepended and/or appended to every Task's `arguments`. The final argument list passed to each Task is:

```
argumentsPrefix + arguments + argumentsPostfix
```

This is useful when many Tasks share a common command structure but differ only in their per-task arguments — the shared parts can be set once at the Work Requirement or Task Group level rather than repeated in every Task definition. Variable substitutions are supported in all three lists.

`argumentsPrefix` and `argumentsPostfix` follow the same inheritance hierarchy as `addEnvironment`: they can be set in the TOML `[workRequirement]` section, at the Work Requirement JSON level, or at the Task Group JSON level (not at the per-Task level), with lower levels taking precedence.

### Example — TOML

```toml
[workRequirement]
    argumentsPrefix = ["--input", "data/"]
    argumentsPostfix = ["--output", "results/"]
    arguments = ["file1.txt"]
    # Effective arguments for each task: ["--input", "data/", "file1.txt", "--output", "results/"]
```

### Example — JSON

In this example, the repeated `python process.py` is set once at the Task Group level; each Task only specifies the part that varies:

```json
{
  "taskGroups": [
    {
      "argumentsPrefix": ["python", "process.py"],
      "tasks": [
        {"arguments": ["--input", "file1.txt"]},
        {"arguments": ["--input", "file2.txt"]},
        {"arguments": ["--input", "file3.txt"]}
      ]
    }
  ]
}
```

Each Task is invoked as `python process.py --input <file>`.

## Task Templates

The `taskTemplate` property on a Task Group optionally sets default values for `taskType`, `taskData`, and `environment` for all Tasks in that group. These defaults are applied by the YellowDog platform, allowing individual Task specifications to be more compact — Tasks that share the same type and data don't need to repeat them.

Any combination of the three fields can be specified; omitted fields are simply not defaulted. Values specified directly on an individual Task take precedence over the template.

`taskDataFile` or `taskDataFiles` can be used inside `taskTemplate` as an alternative to `taskData`, exactly as they can at the Task level — the file contents are read client-side and used as the `taskData` value. `taskDataFiles` concatenates multiple files in order.

`taskTemplate` can be set in the TOML config (applying globally as a default), at the Work Requirement level, or at the Task Group level. More specific levels take precedence.

### Example — TOML

```toml
[workRequirement]
    taskTemplate = {taskType = "docker", taskData = "default-data", environment = {BATCH_SIZE = "100"}}
```

### Example — JSON

```json
{
  "taskGroups": [
    {
      "taskTemplate": {
        "taskType": "docker",
        "taskData": "default-data",
        "environment": {"BATCH_SIZE": "100"}
      },
      "taskTypes": ["docker"],
      "tasks": [
        {},
        {"environment": {"BATCH_SIZE": "200"}},
        {}
      ]
    }
  ]
}
```

All three Tasks use the `docker` task type from the template. The second Task overrides `BATCH_SIZE` to `"200"`; the others inherit `"100"` from the template.

## Automatic Properties

In addition to the property inheritance mechanism, some properties are set automatically by the `yd-submit` command, as a usage convenience if they're not explicitly specified.

### Work Requirement, Task Group and Task Naming

- The **Work Requirement** name is automatically set using a concatenation of the `tag` property, and a UTC timestamp: e.g.: `mytag_221024-15552480`.
- **Task Group** names are automatically created for any Task Group that is not explicitly named, using names of the form `task_group_1` (or `task_group_01`, etc., for larger numbers of Task Groups). Task Group numbers can also be included in user-defined Task Group names using the `{{task_group_number}}` variable substitution discussed below.
- **Task** names are automatically created for any Task that is not explicitly named, using names of the form `task_1` (or `task_01`, etc., for larger numbers of Tasks). The Task counter resets for each different Task Group. Task numbers can also be included in user-defined Task names using the `{{task_number}}` variable substitution discussed below. Automatic Task name generation can be suppressed by setting the `setTaskNames` property to `false`, in which case the `task_name` variable will be set to `none`.

#### Obtaining Names/Context from Environment Variables at Task Run Time

When a Task executes, its Task name and number, Task Group name and number, Work Requirement name, Namespace, and Tag can be made automatically available to the Task in the following environment variables, if the `addYDEnvironment` property is set to `true`:

- `YD_TASK_NAME`
- `YD_TASK_NUMBER`
- `YD_NUM_TASKS` (Number of Tasks in this Task Group)
- `YD_TASK_GROUP_NAME`
- `YD_TASK_GROUP_NUMBER`
- `YD_NUM_TASK_GROUPS` (Number of Task Groups in the Work Requirement)
- `YD_WORK_REQUIREMENT_NAME`
- `YD_NAMESPACE`
- `YD_TAG` (if set at the Task level)

This applies whether the names were set automatically by `yd-submit` or explicitly by the user.

In addition to the environment variables above, when a Task is executed by a Worker, the YellowDog Agent will set the following for use by the Task, based on the instance details and Task identification:

- `YD_PROVIDER`
- `YD_REGION`
- `YD_INSTANCE_TYPE`
- `YD_INSTANCE_ID`
- `YD_TASK_GROUP_ID`
- `YD_TASK_ID`
- `YD_AGENT_DATA`
- `YD_AGENT_HOME`
- `YD_WORKER_SLOT`

### Task and Task Group Counts

The `taskCount` property can be used to expand the number of Tasks within a Task Group, by creating duplicates of a single Task; this can be handy for testing and demos. In JSON specifications, there must be zero or one Task(s) listed within each Task Group or `taskCount` is ignored. This property can also be set on the command line using the `--task-count`/`-C` option of `yd-submit` followed by the required number of Tasks.

Also useful for testing, the `taskGroupCount` property or the command line option `--task-group-count`/`-G` can be set to expand the number of Task Groups in the Work Requirement, by creating duplicates of a single Task Group. If used, the `taskCount` property will apply to every Task Group, i.e., the total number of tasks is the multiple of `taskGroupCount` and `taskGroup`.

## Examples

### TOML Properties in the `workRequirement` Section

Here's an example of the `workRequirement` section of a TOML configuration file, showing all the possible properties that can be set:

```toml
[workRequirement]
    addEnvironment = {EXTRA_VAR = "extra_value", MY_VAR = "override"}
    addYDEnvironment = true
    arguments = ["1", "TWO"]
    argumentsPostfix = ["--postfix-arg"]
    argumentsPrefix = ["--prefix-arg"]
    completedTaskTtl = 10
    csvFile = "file1.csv"
    csvFiles = ["file1.csv", "file3.csv:3"]
    environment = {MY_VAR = 100}
    finishIfAllTasksFinished = true
    finishIfAnyTaskFailed = false
    instancePricingPreference = "SPOT_THEN_ON_DEMAND"
    instanceTypes = ["t3a.micro", "t3.micro"]
    namespaces = ["namespace_1", "namespace_2"]
    maxWorkers = 1
    maximumTaskRetries = 0
    minWorkers = 1
    name = "my-work-requirement"
    parallelBatches = 5
    priority = 0.0
    providers = ["AWS"]
    ram = [0.5, 2.0]
    regions = ["eu-west-2"]
    retryableErrors = [
      {processExitCodes = [143], statusesAtFailure = ["FAILED"], errorTypes = ["ALLOCATION_LOST"]},
    ]
    setTaskNames = false
    tag = "my_tag"
    taskBatchSize = 1000
    taskCount = 100
    taskData = "my_data_string"
    taskDataFile = "my_data_file.txt"
    taskDataFiles = ["header.txt", "body.txt"]
    taskDataInputs = [
      {source = "in_src_path_1", destination = "dest_path_1"},
      {localPath = "local_file", uploadPath = "in_src_path_2", source = "in_src_path_2", destination = "dest_path_2"},
    ]
    taskDataOutputs = [
        {source = "out_src_path_1", destination = "dest_path_1", alwaysUpload = true},
        {source = "out_src_path_2", destination = "dest_path_2", alwaysUpload = false},
    ]
    taskName = "my_task_number_{{task_number}}"
    taskGroupCount = 5
    taskGroupName = "my_task_group_number_{{task_group_number}}"
    taskTemplate = {taskType = "docker", taskData = "my_data_string", environment = {MY_VAR = "value"}}
    taskTimeout = 120.0
    taskType = "docker"
    tasksPerWorker = 1
    vcpus = [1, 4]
    workerTags = ["tag-{{username}}"]
    workRequirementData = "work_requirement.json"
```

### JSON Properties at the Work Requirement Level

Showing all possible properties at the Work Requirement level:

```json
{
  "addEnvironment": {"EXTRA_VAR": "extra_value", "MY_VAR": "override"},
  "addYDEnvironment": true,
  "arguments": [1, "TWO"],
  "argumentsPostfix": ["--postfix-arg"],
  "argumentsPrefix": ["--prefix-arg"],
  "completedTaskTtl": 10,
  "environment": {"MY_VAR": 100},
  "finishIfAllTasksFinished": true,
  "finishIfAnyTaskFailed": false,
  "instancePricingPreference": "SPOT_THEN_ON_DEMAND",
  "instanceTypes": ["t3a.micro", "t3.micro"],
  "maxWorkers": 1,
  "maximumTaskRetries": 0,
  "minWorkers": 1,
  "name": "my-work-requirement",
  "namespaces": ["namespace_1", "namespace_2"],
  "priority": 0.0,
  "providers": ["AWS"],
  "ram": [0.5, 2],
  "regions": ["eu-west-2"],
  "retryableErrors": [
    {
      "processExitCodes": [143],
      "statusesAtFailure" : ["FAILED"],
      "errorTypes": ["ALLOCATION_LOST"]
    }
  ],
  "setTaskNames": false,
  "tag": "my_tag",
  "taskCount": 100,
  "taskData": "my_task_data_string",
  "taskDataFile": "my_data_file.txt",
  "taskDataFiles": ["header.txt", "body.txt"],
  "taskDataInputs": [
    {"destination": "dest_path_1", "source": "in_src_path_1"},
    {"localPath": "local_file", "uploadPath": "in_src_path_2", "destination": "dest_path_2", "source": "in_src_path_2"}
  ],
  "taskDataOutputs": [
    {"alwaysUpload": true, "destination": "dest_path_1", "source": "out_src_path_1"},
    {"alwaysUpload": false, "destination": "dest_path_2", "source": "out_src_path_2"}
  ],
  "taskGroupCount": 5,
  "taskTemplate": {"taskType": "docker", "taskData": "my_task_data_string", "environment": {"MY_VAR": "value"}},
  "taskTimeout": 120.0,
  "taskTypes": ["docker"],
  "tasksPerWorker": 1,
  "vcpus": [1, 4],
  "workerTags": [],
  "taskGroups": [
    {
      "tasks": [
        {}
      ]
    }
  ]
}

```

### JSON Properties at the Task Group Level

Showing all possible properties at the Task Group level:

```json
{
  "taskGroups": [
    {
      "addEnvironment": {"EXTRA_VAR": "extra_value", "MY_VAR": "override"},
      "addYDEnvironment": true,
      "arguments": [1, "TWO"],
      "argumentsPostfix": ["--postfix-arg"],
      "argumentsPrefix": ["--prefix-arg"],
      "completedTaskTtl": 10,
      "environment": {"MY_VAR": 100},
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "instancePricingPreference": "SPOT_THEN_ON_DEMAND",
      "instanceTypes": ["t3a.micro", "t3.micro"],
      "maximumTaskRetries": 0,
      "maxWorkers": 1,
      "minWorkers": 1,
      "name": "first-task-group",
      "namespaces": ["namespace_1", "namespace_2"],
      "priority": 0.0,
      "providers": ["AWS"],
      "ram": [0.5, 2],
      "regions": ["eu-west-2"],
      "retryableErrors": [
        {
          "processExitCodes": [143],
          "statusesAtFailure" : ["FAILED"],
          "errorTypes": ["ALLOCATION_LOST"]
        }
      ],
      "setTaskNames": false,
      "tag": "my_tag",
      "taskCount": 5,
      "taskData": "my_task_data_string",
      "taskDataFile": "my_data_file.txt",
      "taskDataFiles": ["header.txt", "body.txt"],
      "taskDataInputs": [
        {"destination": "dest_path_1", "source": "in_src_path_1"},
        {"localPath": "local_file", "uploadPath": "in_src_path_2", "destination": "dest_path_2", "source": "in_src_path_2"}
      ],
      "taskDataOutputs": [
        {"alwaysUpload": true, "destination": "dest_path_1", "source": "out_src_path_1"},
        {"alwaysUpload": false, "destination": "dest_path_2", "source": "out_src_path_2"}
      ],
      "taskTemplate": {"taskType": "docker", "taskData": "default-data", "environment": {"VAR": "value"}},
      "taskTimeout": 120.0,
      "taskTypes": ["docker"],
      "tasksPerWorker": 1,
      "vcpus": [1, 4],
      "workerTags": [],
      "tasks": [
        {}
      ]
    },
    {
      "name": "second-task-group",
      "dependencies": ["first-task-group"],
      "tasks": [
        {}
      ]
    }
  ]
}
```

### JSON Properties at the Task Level

Showing all possible properties at the Task level:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "addYDEnvironment": true,
          "arguments": [1, 2],
          "environment": {"MY_VAR": 100},
          "name": "my-task",
          "setTaskNames": false,
          "tag": "my_tag",
          "taskData": "my_task_data_string",
          "taskDataFile": "my_data_file.txt",
          "taskDataFiles": ["header.txt", "body.txt"],
          "taskDataInputs": [
            {"destination": "dest_path_1", "source": "in_src_path_1"},
            {"localPath": "local_file", "uploadPath": "in_src_path_2", "destination": "dest_path_2", "source": "in_src_path_2"}
          ],
          "taskDataOutputs": [
            {"alwaysUpload": true, "destination": "dest_path_1", "source": "out_src_path_1"},
            {"alwaysUpload": false, "destination": "dest_path_2", "source": "out_src_path_2"}
          ],
          "timeout": 120.0,
          "taskType": "docker"
        }
      ]
    }
  ]
}
```

## Variable Substitutions in Work Requirement Properties

Variable substitutions can be used within any property value in TOML configuration files or Work Requirement JSON files. See the description [above](#variable-substitutions) for more details on variable substitutions. This is a powerful feature that allows Work Requirements to be parameterised by supplying values on the command line, via environment variables, or via the TOML file.

### Work Requirement Name Substitution

The name of the Work Requirement itself can be used via the variable substitution `{{wr_name}}`. This can be used anywhere in the `workRequirement` section of the TOML configuration file, or in JSON Work Requirement definitions

### Task and Task Group Name Substitutions

The following naming and numbering substitutions are available for use in TOML and JSON Work Requirement specifications, along with the context(s) in which each variable can be used. The variables can be used within the value of any property.

| Directive               | Description                                       | Task | Task Group |
|:------------------------|:--------------------------------------------------|:-----|:-----------|
| `{{task_number}}`       | The current Task number                           | Yes  |            |
| `{{task_name}}`         | The current Task name                             | Yes  |            |
| `{{task_group_name}}`   | The current Task Group name                       | Yes  | Yes        |
| `{{task_count}}`        | The number of Tasks in the current Task Group     | Yes  | Yes        |
| `{{task_group_number}}` | The current Task Group number                     | Yes  | Yes        |
| `{{task_group_count}}`  | The number of Task Groups in the Work Requirement | Yes  | Yes        |

As an example, the following JSON Work Requirement:

```json
{
  "taskGroups": [
    {
      "name": "my_task_group_{{task_group_number}}_a1",
      "taskCount": 2,
      "tasks": [
        {
          "name": "my_task_{{task_number}}-of-{{task_count}}"
        }
      ]
    },
    {
      "name": "my_task_group_{{task_group_number}}_b1",
      "taskCount": 2,
      "tasks": [
        {
          "name": "my_task_{{task_number}}-of-{{task_count}}"
        }
      ]
    }
  ]
}
```

... would create Task Groups named `my_task_group_1_a1` and `my_task_group_2_b1`, each containing Tasks named `my_task_1-of-2`, `my_task_2-of-2`.

## Dry-Running Work Requirement Submissions

To examine the JSON that will actually be sent to the YellowDog API after all processing, use the `--dry-run` (`-D`) command line option when running `yd-submit`. This will print the fully processed JSON for the Work Requirement. Nothing will be submitted to the Platform.

A dry-run is useful for inspecting the results of all the processing that's been performed. To suppress all output except for the JSON itself, add the `--quiet` (`-q`) command line option.

Note that the generated JSON is a **consolidated form** of what would be submitted to the YellowDog API, and Tasks are incorporated directly within their Task Group data structures for ease of comprehension. In actual API submissions, the Work Requirement with zero or more Task Groups is submitted first, and Tasks are then added to their Task Groups separately, in subsequent API calls. Task Groups and Tasks can also later be added to the Work Requirement.

A simple example of the JSON output is shown below, showing a Work Requirement with a single Task Group, containing a single Task.

`% yd-submit --dry-run --quiet`

> **Note:** When used outside of `--dry-run`, `--quiet` on `yd-submit` prints only the Work Requirement YDID to stdout — see [yd-submit](#yd-submit) for scripting examples.

```json
{
  "name": "pyex-docker-pwt_240424-12051160",
  "namespace": "pyexamples-pwt",
  "priority": 0,
  "tag": "pyex-docker-pwt",
  "taskGroups": [
    {
      "finishIfAllTasksFinished": true,
      "finishIfAnyTaskFailed": false,
      "name": "task_group_1",
      "priority": 0,
      "runSpecification": {
        "maximumTaskRetries": 0,
        "taskTypes": ["docker"],
        "workerTags": ["pyex-docker-pwt-worker"]
      },
      "starved": false,
      "waitingOnDependency": false,
      "tasks": [
        {
          "arguments": ["my_dockerhub_repo/my_container_image", "1", "2", "3"],
          "environment": {
            "YD_TASK_NAME": "task_1",
            "YD_TASK_NUMBER": "1",
            "YD_TASK_GROUP_NAME": "task_group_1",
            "YD_TASK_GROUP_NUMBER": "1",
            "YD_WORK_REQUIREMENT_NAME": "pyex-docker-pwt_240424-12051160",
            "YD_NAMESPACE": "pyexamples-pwt"
          },
          "name": "task_1",
          "taskType": "docker"
        }
      ]
    }
  ]
}
```

### Adding Task Groups and Tasks to an Existing Work Requirement

The `--empty` (`-e`) option submits a new Work Requirement with no Task Groups or Tasks (using TOML configuration only, without a JSON spec file), providing a named shell that can be populated later using `--add-to`:

```bash
WR_ID=$(yd-submit --empty --quiet)
yd-submit --add-to "$WR_ID" my-spec.json
```

When a JSON spec file is supplied, empty arrays are honoured directly — `--empty` is not required:

```json
{ "taskGroups": [] }
```

or a Task Group with no tasks:

```json
{
  "taskGroups": [
    { "name": "my-task-group", "tasks": [] }
  ]
}
```

The `--add-to` (`-A`) option allows task groups and/or tasks to be added to a Work Requirement that has already been submitted, as long as it is not in a terminal state.

The argument to `--add-to` is the name or YellowDog ID of the target Work Requirement:

```bash
yd-submit --add-to my-work-requirement my-spec.json
```

The Work Requirement specification supplied is processed in the same way as for a normal submission. The resulting Task Groups are then matched against the Task Groups already present in the target Work Requirement, by name:

- **Matching Task Group name**: the new Tasks are appended to the existing Task Group. Task and Task Group numbers continue from where the existing tasks left off, ensuring consistent naming.
- **New Task Group name**: the Task Group is added to the Work Requirement, and its Tasks are submitted in the normal way.

A single `yd-submit --add-to` invocation can add a mix of new Task Groups and tasks to existing Task Groups simultaneously.

As with a normal `yd-submit`, `--follow` (or `-f`) can be used to follow the Work Requirement to completion after additions have been submitted.

If the spec contains `taskDataInputs` with `localFile` entries, those files will be uploaded to the remote destination as usual. If a file was already uploaded during the original submission and has not changed, it will be skipped by default. Use `--overwrite` (`-O`) to force re-uploading:

```bash
yd-submit --add-to my-work-requirement --overwrite my-spec.json
```

By default, `yd-submit` checks whether a file already exists at the remote destination before uploading, and skips it if so. With `--overwrite`, any file present in the spec is uploaded unconditionally, replacing any existing remote copy.

> **Note:** `--dry-run` is not supported with `--add-to`. Dry-run the specification independently first to inspect its structure before submitting.

### Submitting 'Raw' JSON Work Requirement Specifications

It's possible to use the JSON output of `yd-submit --dry-run` (such as the example above) as a self-contained, fully-specified Work Requirement specification, using the `--json-raw` (or `-j`) command line option, i.e.: `yd-submit --json-raw <filename.json>`.

This will submit the Work Requirement, then add all the specified Tasks.

Note that variable substitutions **can** be used in the raw JSON file, just as in the other Work Requirement JSON examples, but there is no property inheritance, including from the `[workRequirement]` section of the TOML configuration or from Work Requirement properties supplied on the command line.

## Using the YellowDog Data Client

The YellowDog Data Client is described at https://docs.yellowdog.ai/#/the-platform/the-data-client.

The CLI provides full support for expressing Data Client inputs and outputs as part of Task specifications. In addition, it can provide automatic upload of objects on the local filesystem to Data Client targets. It does this using a local `rclone` binary that will be downloaded to your system the first time the Data Client upload capability is used, if `rclone` is not already present. The binary is stored in the Python package's own directory and does not affect any `rclone` already on your `$PATH`. To explicitly upgrade it to the latest version, run `yd-submit --upgrade-rclone`.

Currently, Data Client only supports **individual files**, not directories or wildcards. If multiple, unspecified files are required, we recommend you compress/decompress them into a single file. The compression/decompression can be handled as part of the execution of the Task at its start and/or conclusion.

### Specifying Data Client Inputs

Data Client inputs for Tasks are specified as follows:

TOML, in the `workRequirement` section:

```toml
taskDataInputs = [
  {source = "in_src_path_1", destination = "dest_path_1"},
  {source = "in_src_path_2", destination = "dest_path_2"},
]
```

JSON:

```json
"taskDataInputs": [
  {"destination": "dest_path_1", "source": "in_src_path_1"},
  {"destination": "dest_path_2", "source": "in_src_path_2"}
],
```

- The `source` property must be an rclone-compliant path starting with `rclone:`, e.g.: `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my_bucket_name/directory_name/filename`.
- The `destination` property must specify a local pathname and be prefixed with `local:`, e.g.: `local:my_output.txt`

### Automatic Upload of Local Files

The `yd-submit` command can automatically upload files in the `taskDataInputs` list. This is enabled by adding the `localFile` property, and optionally the `uploadPath` property, to the relevant input specification,  e.g.:

TOML, in the `workRequirement` section:

```toml
taskDataInputs = [
  {localFile = "my_local_file", uploadPath = "in_upload_path_1", source = "in_src_path_1", destination = "dest_path_1"},
]
```

JSON:

```json
"taskDataInputs": [
  {
    "localFile": "my_local_file",
    "uploadPath": "in_upload_path_1",
    "source": "in_src_path_1",
    "destination": "dest_path_1"
  }
]
```

If `uploadPath` is not specified, the local file will be uploaded to the rclone target specified by the `source` property. The local file can be specified using an absolute or relative pathname, and the base files directory can be adjusted using the `--content-path <directory>`/`-F` option supplied to `yd-submit`.

If `yd-submit` fails for any reason, the uploaded objects will be deleted automatically.

### Rclone Authentication

Use of rclone to upload to targets depends on the presence of the required authentication, and this is handled outside the YellowDog CLI.

As an example, if the requirement is to upload to an S3 bucket then appropriate AWS credentials must be present to perform the task, such as `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` being set as environment variables. Example rclone paths could then be:

1. Specifying that the environment should be used for authentication: `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:<bucket-name>/<pathname>`

2. Explicitly using environment variables for authentication: `rclone:S3,type=s3,provider=AWS,access_key_id={{env:AWS_ACCESS_KEY_ID}},secret_access_key={{env:AWS_SECRET_ACCESS_KEY}},region=eu-west-2,location_constraint=eu-west-2:<bucket-name>/<pathname>`. Note that this will include the key ID and secret in plain text in the task specification.

3. Using an rclone configuration file, e.g., referencing a `[mys3]` section in `rclone.conf`: `rclone:mys3:<bucket-name>/<pathname>`.

### Specifying Data Client Outputs

Data Client outputs for Tasks are specified as follows:

TOML, in the `workRequirement` section:
```toml
taskDataOutputs = [
  {source = "out_src_path_1", destination = "dest_path_1"},
  {source = "out_src_path_2", destination = "dest_path_2", alwaysUpload = true},
]
```

JSON:
```json
"taskDataOutputs": [
  {"destination": "dest_path_1", "source": "out_src_path_1"},
  {"destination": "dest_path_2", "source": "out_src_path_2", "alwaysUpload": true}
],
```

- The `source` property must specify a local pathname and be prefixed with `local:`, e.g.: `local:my_output.txt`
- The `destination` property must be an rclone-compliant path, e.g.: `rclone:S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2,location_constraint=eu-west-2:my_bucket_name/directory_name/filename`.

## Task Execution Context

This section discusses the context within which a Task operates when it's executed by a Worker on a node. It applies specifically to the YellowDog Agent running on a Linux node, and configured using the default username, directories, etc. Configurations can vary.

### Task Execution Steps

When a Task is allocated to a Worker on a node by the YellowDog Scheduler, the following steps are followed:

1. The Agent running on the node gets the Task's properties: its `taskType`, `arguments`, `environment`, `taskdata`. A number of `YD_` environment variables are also automatically set by a combination (optionally) of `yd_submit`, and the Agent itself -- see above for details.
2. An ephemeral working directory is created. Data Client input objects are downloaded to this directory, and the contents of the `taskData` property (if set) are written to the file `taskdata.txt`.
3. The Agent runs the command specified for the `taskType` in the Agent's `application.yaml` configuration file. This done as a simple `exec` of a subprocess to run the Task.
4. When the Task concludes, the Agent uses the exit code of the subprocess to report success (zero) or failure (non-zero).
5. The Agent uploads any Data Client outputs specified in `taskDataOutputs` to their destinations. The ephemeral Task directory is then deleted.

Note that if a Task is aborted during execution, the Task's subprocess is sent a `SIGTERM`, allowing the Task an opportunity to terminate any child processes or other resources (e.g., containers) that may have been started as part of Task execution. In addition, there is the option to set an `abort` clause as part of the Task Type specification in the Agent's `application.yaml` file, in which case the script specified in the `abort` clause takes over complete responsibility for any abort handling.

Once the steps above have been completed, the Worker is ready to process its next Task.

Note that if the Agent on a node advertises multiple Workers, then Tasks are executed in parallel on the node and can start and stop independently.

### The User and Group used for Tasks

By default, in the standard YellowDog Agent VM images and in images/instances created using the [YellowDog Agent Installer Script](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md), the Agent runs as user and group `yd-agent`, and hence Tasks also execute under this user.

`yd-agent` does not have `sudo` privileges as standard, but this can be added if required (e.g.) at instance boot time via the `userData` property of a provisioning request. E.g. (for Ubuntu):

```shell
usermod -aG wheel yd-agent
echo -e "yd-agent\tALL=(ALL)\tNOPASSWD: ALL" > /etc/sudoers.d/020-yd-agent
```

### Home Directory for `yd-agent`

By default, the home directory of the `yd-agent` user is `/opt/yellowdog/agent`. This directory typically contains the `application.yaml` file used to configure the Agent, as well as any scripts that are used to execute the Task Types that the node supports.

If one wants to SSH to an instance as user `yd-agent`, perhaps for debugging purposes, SSH keys can be inserted via instance `userData`, e.g.:

```shell
YDA_HOME=/opt/yellowdog/agent
mkdir -p $YDA_HOME/.ssh
chmod og-rwx $YDA_HOME/.ssh
cat >> $YDA_HOME/.ssh/authorized_keys << EOF
<<Insert_Public_key_Here>>
EOF
chmod og-rw $YDA_HOME/.ssh/authorized_keys
chown -R yd-agent:yd-agent $YDA_HOME/.ssh
```

### Task Execution Directory

Ephemeral Task working directories are by default created under `/var/opt/yellowdog/agent/data/workers`, named using their YellowDog Task IDs with colons substituted by underscores.

(On Windows hosts, the Task directories are found under `%AppData%\yellowdog\agent\data\workers`.)

When a Task is started by a worker, an ephemeral directory is created, e.g.:

`/var/opt/yellowdog/agent/data/workers/ydid_task_559EBE_74949336-ac2b-4811-a7d5-f3ecd9739908_1_1`

This is the directory into which downloaded objects are placed, and in which output files are created by default. The console output file, `taskoutput.txt`, containing combined `stderr` and `stdout` output will also be created in this directory.

Note that the Task directory — including `taskoutput.txt` — is **ephemeral**: it is deleted once the Task completes and its outputs have been uploaded. To preserve console output beyond Task execution, add `taskoutput.txt` as a `taskDataOutputs` entry.

## Specifying Work Requirements using CSV Data

CSV data files can be used to drive the generation of lists of Tasks, as follows:

- A **prototype** Task specification is created within a JSON Work Requirement specification or in the `workRequirement` section of the TOML configuration file
- The prototype task includes one or more variable substitutions using the CSV delimiter syntax `<<variable_name>>`
- A CSV file is created, with the **headers** (first row) matching the names of the variable substitutions in the Task prototype
- Each subsequent row of the CSV file represents a new Task to be built using the prototype, with the variables substituted by the values in the row
- A Task will be created for each row of data

Note that CSV substitutions use `<<` and `>>` as delimiters, which is distinct from the `{{` and `}}` delimiters used for general variable substitutions. This means that regular variable substitutions (e.g. `{{namespace}}`) can coexist with CSV substitutions in the same Task prototype without ambiguity.

### Work Requirement CSV Data Example

As an example, consider the following JSON Work Requirement `wr.json`:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["<<arg_1>>", "<<arg_2>>", "<<arg_3>>"],
          "environment": {"ENV_VAR_1": "<<env_1>>"}
        }
      ]
    }
  ]
}
```

Note that the Task Group must contain only a single Task, acting as the prototype.

Now consider a CSV file `wr_data.csv` with the following contents:

```text
arg_1, arg_2, arg_3, env_1
A,     B,     C,     E-1
D,     E,     F,     E-2
G,     H,     I,     E-3
```

Note that the (optional) leading spaces after each comma are ignored, but trailing spaces are not and will form part of the imported data.

If these files are processed using `yd-submit wr.json -V wr_data.csv`, the following expanded list of three Tasks will be created prior to further processing by the `yd-submit` script:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["A", "B", "C"],
          "environment": {"ENV_VAR_1": "E-1"}
        },
        {
          "arguments": ["D", "E", "F"],
          "environment": {"ENV_VAR_1": "E-2"}
        },
        {
          "arguments": ["G", "H", "I"],
          "environment": {"ENV_VAR_1": "E-3"}
        }
      ]
    }
  ]
}
```

### CSV Variable Substitutions

When the CSV file data is processed, the only substitutions made are those which match the variable substitutions in the prototype Task. The CSV file is the **only** source of substitutions used for this processing phase; all other variable substitutions (supplied on the command line, in the TOML configuration file, or from environment variables) are ignored -- i.e., they do not override the contents of the CSV file.

All variable substitutions unrelated to the CSV file data are left unchanged, for subsequent processing by `yd-submit`.

If the value to be inserted is a number (an integer or floating point value) or Boolean, the `<<num:my_number_var>>` and `<<bool:my_boolean_var>>` forms can be used in the JSON file. The substituted value will assume the nominated type rather than being a string. (The `array:` and `table:` prefixes are not currently supported for CSV substitutions.)

### Property Inheritance

All the usual property inheritance features operate as normal. Properties are inherited from the `config.toml` file, and from the relevant sections of the JSON Work Requirement file. Any properties set within a Task prototype are copied to all the generated Tasks.

### Multiple Task Groups using Multiple CSV Files

The use of multiple Task Groups is also supported, by using one CSV file per Task Group. Each Task Group must contain only a single prototype Task.

The CSV files are supplied on the command line in the order of the Task Groups to which they apply. For example, if `wr_json` contains two Task Groups, as follows:

```json
{
  "taskGroups": [
    {
      "tasks": [
        {
          "arguments": ["<<arg_1>>", "<<arg_2>>", "<<arg_3>>"],
          "environment": {"ENV_VAR_1": "<<env_1>>"}
        }
      ]
    },
    {
      "tasks": [
        {
          "arguments": ["<<arg_1>>", "<<arg_2>>"],
          "environment": {"ENV_VAR_1": "<<env_1>>", "ENV_VAR_2": "<<env_2>>"}
        }
      ]
    }
  ]
}
```

The `yd-submit` command would then be invoked with a separate CSV file for each Task Group, e.g.:

```shell
yd-submit wr.json -V wr_data_task_group_1.csv -V wr_data_task_group_2.csv
```

If there are **fewer** CSV files than Task Groups a warning will be printed and, if there are 'n' CSV files, CSV data processing will be applied to the first 'n' Task Groups in the Work Requirement by default, in the order in which the CSV files were supplied. If there are **more** CSV files than Task Groups, an error will be raised and processing will stop.

It is possible to apply CSV files explicitly to specific Task Groups, by using an optional **index postfix** (e.g., `:2`) at the end of each CSV filename. For example, if there are two CSV files to be applied to the second and fourth Task Groups in a JSON Work Requirement, use the following syntax:

```shell
yd-submit wr.json -V wr_data_task_group_2.csv:2 -V wr_data_task_group_4.csv:4
```

Alternatively, the **Task Group name** (if supplied in the JSON file) can be used as the postfix. For example, if the Task Groups above are named `tg_two` and `tg_four`, the `yd-submit` command would become:

```shell
yd-submit wr.json -V wr_data_task_group_2.csv:tg_two -V wr_data_task_group_4.csv:tg_four
```

Note that only one CSV file can be applied to any given Task Group. A single CSV file can, however, be reused for multiple Task Groups.

### Using CSV Data with Simple, TOML-Only Work Requirement Specifications

It's possible to use TOML exclusively to derive a list of Tasks from CSV data -- i.e., a JSON Work Requirement specification is not required.

To make use of this:

1. Ensure that no JSON Work Requirement document is specified (no `workRequirementData` in the TOML file, or no positional argument on the command line)
2. Insert the required CSV-supplied variable substitutions directly into the TOML properties, e.g. `arguments = ["<<arg_1>>", "<<arg_2>>"]`
3. Specify a single CSV file in the `csvFiles` TOML property, e.g. `csvFiles = ["wr_data.csv"]`, or provide the CSV file on the command line `-V wr_data.csv`

When `yd-submit` is run, it will expand the Task list to match the number of data rows in the CSV file.

### Inspecting the Results of CSV Variable Substitution

The `--process-csv-only` (or `-p`) option can be used with `yd-submit` to output the JSON Work Requirement after CSV variable substitutions only, prior to all other substitutions and property inheritance applied by `yd-submit`.

# Worker Pools

A Provisioned **Worker Pool** is a set of cloud-provisioned compute instances running the YellowDog agent, which claim and execute Tasks from Work Requirements. Worker Pools are created using the **`yd-provision`** command and are automatically scaled and shut down based on demand and configured timeout settings.

**Jump to:** [Property Dictionary](#worker-pool-properties) · [TOML Example](#toml-properties-in-the-workerpool-section) · [JSON Spec](#worker-pool-specification-using-json-documents) · [Variable Substitutions](#variable-substitutions-in-worker-pool-properties) · [Dry-Running](#dry-running-worker-pool-provisioning) · [Node Actions](#node-actions)

The `workerPool` section of the TOML file defines the properties of the Worker Pool to be created, and is used by the `yd-provision` command. A subset of the properties is also used by the `yd-instantiate` command, for creating standalone Compute Requirements that are not associated with Worker Pools. Note that `computeRequirement` may be used as a synonym for `workerPool`, and the two may be used simultaneously in the same TOML file provided that their contained properties are not duplicated.

The only mandatory property is `templateId`. All other properties have defaults (or are not required). 
The `templateId` property can use either the YellowDog ID ('YDID') for the Compute Requirement Template, or its name.

## Worker Pools vs. Compute Requirements

It is worth clarifying the distinction between the two related concepts:

- A **Worker Pool** (created by `yd-provision`) is a managed set of cloud instances running the YellowDog agent. The platform automatically scales the pool up and down to meet Task demand, and shuts it down when idle. Worker Pool nodes claim Tasks from Work Requirements and execute them.

- A **Compute Requirement** (created by `yd-instantiate`) is simply a set of cloud instances — there is no YellowDog Worker Pool associated with them. The instances are managed directly by the user. This is useful when you want to use YellowDog's provisioning capabilities but manage instances yourself.

Both use the same `workerPool` / `computeRequirement` TOML section for configuration, and both are terminated using `yd-terminate`.

## Worker Pool Properties

The following properties are available:

| Property                | Description                                                                                                                                       | Default                 |
|:------------------------|:--------------------------------------------------------------------------------------------------------------------------------------------------|:------------------------|
| `computeRequirementBatchSize` | The maximum number of instances per Compute Requirement batch (see [Large-Scale Provisioning](#large-scale-provisioning)). Values above 10,000 are clamped to 10,000. | `10000` |
| `computeRequirementData` | The name of a file containing a JSON specification of a Compute Requirement; used by `yd-instantiate` (see [yd-instantiate](#yd-instantiate)).  |                         |
| `idleNodeTimeout`       | The timeout in minutes after which an idle node will be shut down. Set this to `0` to disable the timeout.                                        | `5.0`                   |
| `idlePoolTimeout`       | The timeout in minutes after which an idle Worker Pool will be shut down. Set this to `0` to disable the timeout.                                 | `30.0`                  |
| `imagesId`              | The Image ID, Image Family ID, Image Family name, or Image Group name to use when booting instances.                                              |                         |
| `instanceTags`          | The dictionary of instance tags to apply to the instances. Tag names must be lower case.                                                          |                         |
| `maintainInstanceCount` | Only used when instantiating Compute Requirements; attempt to maintain the requested number of instances.                                         | `false`                 |
| `maxNodes`              | The maximum number of nodes to which the Worker Pool can be scaled up.                                                                            | `1`                     |
| `metricsEnabled`        | Whether to enable performance metrics for nodes in the Worker Pool                                                                                | `false`                 |
| `minNodes`              | The minimum number of nodes to which the Worker Pool can be scaled down.                                                                          | `0`                     |
| `name`                  | The name of the Worker Pool.                                                                                                                      | Automatically Generated |
| `nodeBootTimeout`       | The time in minutes allowed for a node to boot and register with the platform, otherwise it will be terminated.                                   | `10.0`                  |
| `requirementTag`        | The tag to apply to the Compute Requirement.                                                                                                      | `tag` set in `common`   |
| `targetInstanceCount`   | The initial number of nodes to create in the Worker Pool.                                                                                         | `1`                     |
| `templateId`            | The YellowDog Compute Requirement Template ID or name to use for provisioning. (**Required**)                                                     | No default provided     |
| `userData`              | User Data to be supplied to instances on boot.                                                                                                    |                         |
| `userDataFile`          | As above, but read the User Data from the filename supplied in this property.                                                                     |                         |
| `userDataFiles`         | As above, but create the User Data by concatenating the contents of the list of filenames supplied in this property.                              |                         |
| `workerPoolData`        | The name of a file containing a JSON specification of a Worker Pool (see [Worker Pool JSON](#worker-pool-specification-using-json-documents)).    |                         |
| `workerTag`             | The Worker Tag to publish for each of the Workers on the node(s).                                                                                 |                         |
| `workersPerNode`        | The number of Workers to establish on each node in the Worker Pool. Mutually exclusive with `workersPerVCPU` and `workersCustomCommand`.          | `1`                     |
| `workersPerVCPU`        | The number of Workers to establish per vCPU on each node in the Worker Pool. Mutually exclusive with `workersPerNode` and `workersCustomCommand`. |                         |
| `workersCustomCommand`  | A command run on the node to determine the number of Workers to establish. Mutually exclusive with `workersPerNode` and `workersPerVCPU`.         |                         |

## Using Textual Names instead of IDs for Compute Requirement Templates and Image Families

The `templateId` property can be directly populated with the YellowDog ID (YDID), or it can be populated with the textual name of the template, in the form `namespace/template_name`.

Similarly, the `imagesId` property can be populated with the YDID of an Image Family, Image Group, Image, or a string representing the native name of a cloud provider image (e.g., an AWS AMI). It can also be populated with an Image Family name in the form `namespace/image_family_name`, or an Image Group name in the form `namespace/image_family_name/image_group_name` or `image_family_name/image_group_name`. Optionally, a `yd/` prefix can be supplied. The CLI will aim to map the provided name into an Image Family or Group YDID.

## Large-Scale Provisioning

The platform limits each Compute Requirement and Worker Pool to **10,000 instances/nodes**. When `targetInstanceCount` (for `yd-instantiate`) or `maxNodes` (for `yd-provision`) exceeds this limit, the CLI automatically splits the request across multiple Compute Requirements, distributing instances as evenly as possible.

The `computeRequirementBatchSize` property controls the maximum number of instances per batch and defaults to 10,000 (the platform maximum). Set it to a smaller value to submit in smaller batches. Values above 10,000 are clamped to 10,000 with a warning.

## Automatic Properties

The name of the Worker Pool, if not supplied, is automatically generated using a concatenation of `wp_`, the `tag` property, and a UTC timestamp, e.g.: `wp_mytag_221024-155524`.

## TOML Properties in the `workerPool` Section

Here's an example of the `workerPool` section of a TOML configuration file, showing all the possible properties that can be set:

```toml
[workerPool]
    idleNodeTimeout = 10.0
    idlePoolTimeout = 60.0
    imagesId = "ydid:imgfam:000000:41962592-577c-4fde-ab03-d852465e7f8b"
    instanceTags = {}
    maxNodes = 1
    minNodes = 1
    metricsEnabled = true
    name = "my-worker-pool"
    nodeBootTimeout = 5
    requirementTag = "my_tag"
    targetInstanceCount = 1
    templateId = "ydid:crt:D9C548:465a107c-7cea-46e3-9fdd-15116cb92c40"
    # Note: only one of 'userData'/'userDataFile'/'userDataFiles' should be set
    userData = ""
    # userDataFile = "myuserdata.txt"
    # userDataFiles = ["myuserdata1.txt", "myuserdata2.txt"]
    workerTag = "tag-{{username}}"
    # Specify either workersPerNode, workersPerVCPU, or workersCustomCommand
    workersPerNode = 1
    # workersPerVCPU = 1
    # workersCustomCommand = "calc-my-worker-count.sh"
    # workerPoolData = "worker_pool.json"  # Optionally specify worker pool JSON specification
```

## Worker Pool Specification Using JSON Documents

It's also possible to capture a Worker Pool definition as a JSON document. The JSON filename can be supplied either by supplying the command line positional argument for `yd-provision`, or by populating the `workerPoolData` property in the TOML configuration file with the JSON filename. Command line specification takes priority over TOML specification.

The JSON specification allows the creation of **Advanced Worker Pools**, with the ability to specify Node Actions and to differentiate Node Types.

When using a JSON document to specify the Worker Pool, the schema of the document is identical to that expected by the YellowDog REST API for Worker Pool Provisioning.

### Worker Pool JSON Examples

The example below is of a simple JSON specification of a Worker Pool with one initial node, Worker Pool shutdown, etc.

```json
{
  "requirementTemplateUsage": {
    "maintainInstanceCount": false,
    "requirementName": "wp_pyex-primes_230113-161528",
    "requirementNamespace": "pyexamples",
    "requirementTag": "pyex-primes",
    "targetInstanceCount": 1,
    "templateId": "ydid:crt:D9C548:465a107c-7cea-46e3-9fdd-15116cb92c40"
  },
  "provisionedProperties": {
    "idleNodeShutdown": {"enabled": true, "timeout": "PT10M"},
    "idlePoolShutdown": {"enabled": true, "timeout": "PT1H"},
    "createNodeWorkers": {"targetCount": 1, "targetType": "PER_VCPU"},
    "maxNodes": 5,
    "metricsEnabled": true,
    "minNodes": 0,
    "nodeBootTimeout": "PT5M",
    "nodeIdleGracePeriod": "PT3M",
    "nodeIdleTimeLimit": "PT3M",
    "workerTag": "pyex-bash-docker"
  }
}
```

The next example is of a more complex JSON specification of an Advanced Worker Pool, from one of the YellowDog demos. It includes node specialisation, and action groups that respond to the `STARTUP_NODES_ADDED` and `NODES_ADDED` events to drive **Node Actions**.

```json
{
  "requirementTemplateUsage": {
    "maintainInstanceCount": false
  },
  "provisionedProperties": {
    "createNodeWorkers": {"targetCount": 0, "targetType": "PER_NODE"},
    "nodeConfiguration": {
      "nodeTypes": [
        {"name": "slurmctld", "count": 1},
        {"name": "slurmd", "min": 2, "slotNumbering": "REUSABLE"}
      ],
      "nodeEvents": {
        "STARTUP_NODES_ADDED": [
          {
            "actions": [
              {
                "action": "WRITE_FILE",
                "path": "nodes.json",
                "content": "{\"nodes\":[{{#otherNodes}}{\"name\":\"slurmd{{details.nodeSlot}}\",\"ip\":\"{{details.privateIpAddress}}\"}{{^-last}},{{/-last}}{{/otherNodes}}]}",
                "nodeTypes": ["slurmctld"]
              },
              {
                "action": "RUN_COMMAND",
                "path": "start_simple_slurmctld",
                "arguments": ["nodes.json"],
                "nodeTypes": ["slurmctld"]
              }
            ]
          },
          {
            "actions": [
              {
                "action": "RUN_COMMAND",
                "path": "start_simple_slurmd",
                "arguments": ["{{nodesByType.slurmctld.0.details.privateIpAddress}}", "{{node.details.nodeSlot}}"],
                "nodeTypes": ["slurmd"]
              }
            ]
          },
          {
            "actions": [
              {
                "action": "CREATE_WORKERS",
                "totalWorkers": 1,
                "nodeTypes": ["slurmctld"]
              }
            ]
          }
        ],
        "NODES_ADDED": [
          {
            "actions": [
              {
                "action": "WRITE_FILE",
                "path": "nodes.json",
                "content": "{\"nodes\":[{{#filteredNodes}}{\"name\":\"slurmd{{details.nodeSlot}}\",\"ip\":\"{{details.privateIpAddress}}\"}{{^-last}},{{/-last}}{{/filteredNodes}}]}",
                "nodeTypes": ["slurmctld"]
              },
              {
                "action": "RUN_COMMAND",
                "path": "add_nodes",
                "arguments": ["nodes.json"],
                "nodeTypes": ["slurmctld"]
              }
            ]
          },
          {
            "actions": [
              {
                "action": "RUN_COMMAND",
                "path": "start_simple_slurmd",
                "arguments": ["{{nodesByType.slurmctld.0.details.privateIpAddress}}", "{{node.details.nodeSlot}}"],
                "nodeIdFilter": "EVENT",
                "nodeTypes": ["slurmd"]
              }
            ]
          }
        ]
      }
    }
  }
}
```

### TOML Properties Inherited by Worker Pool JSON Specifications

When a JSON Worker Pool specification is used, the following properties from the `config.toml` file will be inherited if the value is absent in the JSON file:

**Properties Inherited within the `requirementTemplateUsage` property**

- `imagesId`
- `instanceTags`
- `requirementName`: obtained from the `name` property in the TOML configuration. (The name will be generated automatically if not supplied in either the TOML file or the JSON specification.)
- `requirementNamespace`: obtained from the `namespace` property in the `TOML` configuration
- `requirementTag`: obtained from the `requirementTag` property at the `workerPool` level, or the `tag` in the `common` configuration
- `targetInstanceCount`
- `templateId`
- `userData`
- `userDataFile`
- `userDataFiles`

Note that the `templateId` property can use either the YellowDog ID ('YDID') for the Compute Requirement Template, or its name. Similarly, the `imagesId` property can use either a YDID or the Image Family or Image Group name (e.g, `"yd-agent-docker"`).

**Properties Inherited within the `provisionedProperties` Property**

- `idleNodeTimeout` (set to `0` to disable)
- `idlePoolTimeout` (set to `0` to disable)
- `maxNodes`
- `metricsEnabled`
- `minNodes`
- `nodeBootTimeout`
- `workerTag`
- `workersPerNode`, `workersPerVCPU`, or `workersCustomCommand` (Note that the default value for `workersPerNode` is `1`; override this with `workersPerNode = 0` if required)

## Variable Substitutions in Worker Pool Properties

Variable substitutions can be used within any property value in TOML configuration files or Worker Pool JSON files. See the description [above](#variable-substitutions) for more details on variable substitutions. This is a powerful feature that allows Worker Pools to be parameterised by supplying values on the command line, via environment variables, or via the TOML file.

An important distinction when using variable substitutions within Worker Pool (or Compute Requirement) JSON/Jsonnet documents is that each variable directive **must be prefixed and postfixed by a `__` (double underscore)** to disambiguate it from Mustache variable substitutions that must be passed directly to the API without client processing. For example, use: `__{{username}}__` to apply a substitution for the `username` default variable substitution.

In general, double underscores are **not** required in variable substitutions within the `workerPool` and/or `computeRequirement` sections of a TOML file. The exception to this is if the `userData` property is supplied, in which case double underscores **are** required. They are also required within any files referenced by the `userDataFile` or `userDataFiles` properties.

## Dry-Running Worker Pool Provisioning

To examine the JSON that will actually be sent to the YellowDog API after all processing, use the `--dry-run` command line option when running `yd-provision`. This will print the JSON specification for the Worker Pool. Nothing will be submitted to the platform.

The generated JSON is produced after all processing (incorporating `config.toml` properties, variable substitutions, etc.) has been concluded, so the dry-run is useful for inspecting the results of all the processing that's been performed.

To suppress all output except for the JSON itself, add the `--quiet` (`-q`) command line option.

Use `--follow` (`-f`) to track the provisioning progress after submission — `yd-provision` will report on node events and not return until the Worker Pool reaches a stable state.

The JSON dry-run output could itself be used by `yd-provision`, if captured in a file, e.g.:

```shell
yd-provision --dry-run -q > my_worker_pool.json
yd-provision my_worker_pool.json
```

## Node Actions

Node Actions allow scripts and commands to be dispatched directly to running Worker Pool nodes. They can be used to start services (e.g., Slurm controllers), write configuration files, or create YellowDog Workers dynamically — without modifying the original Worker Pool specification. Node Actions are submitted using the **`yd-nodeaction`** command.

### Action Types

There are three action types:

| Type            | Description                          |
|:----------------|:-------------------------------------|
| `runCommand`    | Execute a command on the node        |
| `writeFile`     | Write a file to the node             |
| `createWorkers` | Create YellowDog Workers on the node |

### Spec File Structure

Node actions are defined in a JSON (or Jsonnet) spec file supplied via the `--actions` option. The spec is a JSON object containing either an `actions` key (a flat list of actions) or an `actionGroups` key (a list of action groups, where an action group is a flat list of actions).

Actions in an actions list are downloaded by a node in one operation and executed sequentially.

Variable substitutions in spec files must use the `__{{variable}}__` prefix/postfix convention (the same as Worker Pool and Compute Requirement specs), since the content may include Mustache templates that the platform processes server-side.

#### Actions

Actions are submitted to one or more specific nodes, or broadcast to all nodes in the pool, and optionally filtered by `nodeTypes`:

```json
{
  "actions": [
    {
      "type": "runCommand",
      "path": "/usr/local/bin/configure.sh",
      "arguments": ["--region", "__{{region:=us-east-1}}__"],
      "environment": {"CLUSTER_NAME": "__{{tag}}__"},
      "nodeTypes": ["controller"]
    },
    {
      "type": "writeFile",
      "path": "/etc/myapp/config.json",
      "content": "{\"endpoint\": \"__{{endpoint}}__\"}"
    },
    {
      "type": "createWorkers",
      "nodeWorkers": {
        "targetType": "PER_VCPU",
        "targetCount": 1
      }
    }
  ]
}
```

#### Action Groups

Grouped actions are submitted as a unit to the pool, but actions are executed by nodes one group at a time:

```json
{
  "actionGroups": [
    {
      "actions": [
        {
          "type": "runCommand",
          "path": "start_controller.sh",
          "nodeTypes": ["slurmctld"]
        },
        {
          "type": "createWorkers",
          "nodeWorkers": {"targetType": "PER_NODE", "targetCount": 1},
          "nodeTypes": ["slurmctld"]
        }
      ]
    },
    {
      "actions": [
        {
          "type": "runCommand",
          "path": "start_worker.sh",
          "nodeTypes": ["slurmd"]
        }
      ]
    }
  ]
}
```

### Action Fields Reference

#### Common Fields (all action types)

| Field       | Description                                                    | Required |
|:------------|:---------------------------------------------------------------|:---------|
| `type`      | Action type: `runCommand`, `writeFile`, or `createWorkers`     | Yes      |
| `nodeTypes` | Restrict to nodes whose type name matches one of these strings | No       |

#### `runCommand` Fields

| Field         | Description                                         | Required |
|:--------------|:----------------------------------------------------|:---------|
| `path`        | Path to the command to execute on the node          | Yes      |
| `arguments`   | List of command-line argument strings               | No       |
| `environment` | Dictionary of environment variable name/value pairs | No       |

#### `writeFile` Fields

| Field          | Description                                                                              | Required |
|:---------------|:-----------------------------------------------------------------------------------------|:---------|
| `path`         | Destination file path on the node                                                        | Yes      |
| `content`      | File content as a string                                                                 | No       |
| `contentFile`  | Path to a local file whose content is read and written to the node                       | No       |
| `contentFiles` | List of local file paths whose contents are concatenated and written to the node         | No       |

The `content`, `contentFile`, and `contentFiles` properties are mutually exclusive. All support variable substitutions using the `__{{variable}}__` convention.

#### `createWorkers` Fields

| Field          | Description                                   | Required |
|:---------------|:----------------------------------------------|:---------|
| `nodeWorkers`  | Worker target specification (see table below) | No       |
| `totalWorkers` | Fixed total number of workers to create       | No       |

**`nodeWorkers` sub-fields:**

| Field                 | Description                                                      |
|:----------------------|:-----------------------------------------------------------------|
| `targetType`          | `"PER_NODE"`, `"PER_VCPU"`, or `"CUSTOM"`                        |
| `targetCount`         | Worker count per node or per vCPU (for `PER_NODE` or `PER_VCPU`) |
| `customTargetCommand` | Command to run to determine the worker count (for `CUSTOM`)      |

### Node Selection

When submitting actions, target nodes are specified in one of three ways:

- **`--node <id>`**: Submit to a specific node; can be repeated for multiple nodes. If the value is a node YDID, the Worker Pool is resolved automatically without prompting.
- **`--all-nodes`**: Broadcast to all current nodes in the pool.
- **Interactive**: If neither flag is given, the worker pool's current nodes are displayed for interactive selection.

For grouped actions, `--all-nodes` applies the groups to all nodes; `--node` restricts them to the specified node IDs; omitting both offers interactive node selection.

### Worker Pool Selection

The `--worker-pool` option accepts either a Worker Pool name or a Worker Pool YDID. If omitted, an interactive selection prompt is shown (filtered by the configured `namespace` and `tag`).

When `--node` is given with explicit node YDIDs and `--worker-pool` is omitted, the Worker Pool is resolved automatically from the node, skipping the selection prompt.

### Checking Node Action Queue Status

The `--status` flag displays the action queue for selected node(s) as a single consolidated table. Use `--details` for the full JSON representation of each queue:

```shell
yd-nodeaction --status --worker-pool my-pool
yd-nodeaction --status --node ydid:node:D9C548:abc123...
yd-nodeaction --status --node ydid:node:D9C548:abc123... --details
```

When `--node` is given with a node YDID, `--status` goes directly to the node without prompting for a Worker Pool.

The summary table shows, for each node: Node ID, queue status, count of waiting actions, the currently executing action, and any failed action.

### Following Progress

Use `--follow` to poll the node action queues after submission, printing a status table every few seconds until all queues reach `EMPTY` or `FAILED`:

```shell
yd-nodeaction --actions actions.json --node ydid:node:D9C548:abc123... --follow
```

`--follow` also works with `--all-nodes`; the current node list is fetched from the Worker Pool at follow time.

`--follow` can also be combined with `--status` to poll an already-running queue without submitting new actions:

```shell
yd-nodeaction --status --node ydid:node:D9C548:abc123... --follow
```

# Data Client

The `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy` commands provide direct access to remote data stores (object storage buckets) via **[rclone](https://rclone.org)**. They do **not** require a YellowDog Application key or secret — only the data store connection details.

The `rclone` binary will be automatically downloaded if not already present.

These commands share a common `[dataClient]` TOML configuration section:

```toml
[dataClient]
    remote = "myremote"               # rclone remote name (from rclone.conf) or inline connection string
    bucket = "my-bucket"              # bucket / container / root path (see note below)
    prefix = "{{namespace}}/{{tag}}"  # path prefix within the bucket (default: namespace/tag)
```

The `remote`, `bucket`, and `prefix` values can also be supplied via command line options (`--remote`/`-r`, `--bucket`/`-b`, `--prefix`/`-p`) or environment variables (`YD_DATA_CLIENT_REMOTE`, `YD_DATA_CLIENT_BUCKET`, `YD_DATA_CLIENT_PREFIX`). The `--no-prefix` flag disables the prefix entirely.

The `remote` field accepts either:
- A plain remote name defined in the system `rclone.conf` (e.g., `"yds3"`)
- An inline rclone connection string (e.g., `"S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2"`)
- An `rclone:` prefix can optionally be included

The default prefix is `{{namespace}}/{{tag}}`, using the `namespace` and `tag` values from the `[common]` section (or their environment variable / command line equivalents). Variable substitutions (`{{...}}`) are supported in all `[dataClient]` values and also in the remote path arguments passed to `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy` on the command line. All built-in variables (`{{namespace}}`, `{{tag}}`, `{{username}}`, `{{date}}`, etc.) and user-defined variables (`YD_VAR_*` / `[common.variables]`) are available. Arguments containing `{{...}}` should be quoted to prevent shell interpretation.

> **Note on `bucket`:** The `bucket` property is named after S3/GCS terminology but applies equally to other rclone storage backends — use it to specify the container name (Azure Blob Storage), the root directory (SFTP, local, Google Drive), or the equivalent top-level path component for your storage target.

## Named Profiles

Multiple named profiles can be defined as sub-tables of `[dataClient]`. A named profile overrides only the fields it specifies; any field not set in the profile inherits the corresponding value from the base `[dataClient]` section.

```toml
[dataClient]
prefix = "{{namespace}}/{{tag}}"   # shared default inherited by all profiles

[dataClient.prod]
remote = "s3-prod"
bucket = "prod-data"

[dataClient.staging]
remote = "s3-staging"
bucket = "staging-data"
# inherits prefix from [dataClient]
```

Select a profile with `--data-client-profile <name>`:

```
yd-upload --data-client-profile prod myfile.txt
yd-download --data-client-profile staging results/
```

The active profile can also be set via the `YD_DATA_CLIENT` environment variable. The `--remote`, `--bucket`, `--prefix`, and `--no-prefix` flags still apply on top of the selected profile, so individual fields can be overridden per invocation.

Profile names are free-form; the only reserved names are `remote`, `bucket`, and `prefix` (the scalar field names of `[dataClient]` itself).

## Variable Substitutions for Data Client Properties

The `remote`, `bucket`, and `prefix` values from `[dataClient]` are available as variable substitutions in all spec files (TOML, JSON, Jsonnet) and in `userdata` scripts for every command — including `yd-submit`, `yd-provision`, and `yd-instantiate`:

| Variable | Value |
|---|---|
| `{{dataClient.remote}}` | Active profile's remote (or base `[dataClient].remote`) |
| `{{dataClient.bucket}}` | Active profile's bucket |
| `{{dataClient.prefix}}` | Active profile's prefix |
| `{{dataClient.<name>.remote}}` | Named profile's remote, regardless of active selection |
| `{{dataClient.<name>.bucket}}` | Named profile's bucket |
| `{{dataClient.<name>.prefix}}` | Named profile's prefix |

For `yd-upload`/`yd-download`/`yd-delete`/`yd-ls`/`yd-copy`, `{{dataClient.remote/bucket/prefix}}` reflects the fully-resolved active source profile (after `--data-client-profile` selection, env vars, and CLI overrides). For all other commands, it reflects the base `[dataClient]` section.

Named profile variables are always resolved with profile fields taking precedence over the base section, so `{{dataClient.prod.prefix}}` gives the prod profile's prefix (or the base prefix if not set in `[dataClient.prod]`).

> **Note on Worker Pool / Compute Requirement specs and User Data:** In JSON/Jsonnet Worker Pool and Compute Requirement specifications, and in all User Data (whether supplied via `userData`, `userDataFile`, or `userDataFiles`), variable substitutions **must be prefixed and postfixed by double underscores** to disambiguate them from server-side Mustache processing. Use `__{{dataClient.remote}}__`, `__{{dataClient.prod.bucket}}__`, etc.

Example use in a work requirement spec (no underscores needed in WR JSON):

```json
{
  "taskDataInputs": [
    {
      "source": "{{dataClient.remote}}:{{dataClient.bucket}}/{{dataClient.prefix}}/input.csv",
      "destination": "input.csv"
    }
  ]
}
```

Example use in a `userdata` script (double underscores required):

```bash
#!/bin/bash
rclone copy __{{dataClient.prod.remote}}__:__{{dataClient.prod.bucket}}__/configs /tmp/configs
```

## yd-upload

The `yd-upload` command uploads local files or directories to a remote data store.

```
yd-upload [options] <local_path> [<local_path> ...]
```

Key options:
- `--recursive`/`-R` — upload directories recursively, preserving the directory structure
- `--flatten` — upload all files in a directory tree to a flat (single-level) remote destination
- `--sync` — synchronise the remote destination to match the local source (implies `--recursive`); files present at the destination but absent locally are deleted
- `--destination`/`-d <remote_path>` — override the destination path; supports `{{variable}}` substitution
- `--dry-run`/`-D` — show what would be uploaded without actually uploading

## yd-download

The `yd-download` command downloads files from a remote data store to a local directory.

```
yd-download [options] <remote_path> [<remote_path> ...]
```

Key options:
- `--sync` — mirror the remote source to the local destination, deleting local files not present remotely (not compatible with `--flatten`)
- `--flatten` — download all files in a remote directory tree to a flat (single-level) local destination
- `--destination`/`-d <local_path>` — local destination directory (default: mirrors the remote directory name)
- `--dry-run`/`-D` — show what would be downloaded without actually downloading

Remote paths support `{{variable}}` substitution (e.g., `'{{tag}}/results.csv'`) and may also contain wildcard characters (`*`, `?`, `[…]`). A wildcard path is expanded against the configured prefix and all matching files and directories are downloaded. The matched names are displayed before the download begins. When a wildcard is used, files are downloaded into the current directory (preserving the names of the matched items) unless `--destination` is specified. `--sync` is supported with wildcards.

Example: `yd-download 'results_*'` downloads everything whose name starts with `results_`.

## yd-delete

The `yd-delete` command deletes files or directories from a remote data store. `yd-rm` is a synonym.

```
yd-delete [options] [<remote_path> ...]
```

If no remote paths are specified, the command operates on the entire configured prefix. Use `--recursive` to delete a directory tree.

Key options:
- `--recursive`/`-R` — recursively delete a remote directory tree
- `--dry-run`/`-D` — show what would be deleted without actually deleting
- `--yes`/`-y` — skip confirmation prompts

Remote paths support `{{variable}}` substitution and may also contain wildcard characters (`*`, `?`, `[…]`). The wildcard is expanded first and the matched names are displayed; confirmation is then requested before any deletions take place. Matching directories require `--recursive` to be deleted.

Example: `yd-delete 'results_*'` deletes all items whose name starts with `results_`.

## yd-ls

The `yd-ls` command lists files and directories in a remote data store.

```
yd-ls [options] [<remote_path> ...]
```

If no remote paths are specified, the configured prefix is listed.

Key options:
- `--recursive`/`-R` — list recursively; output is displayed as a directory tree

Remote paths support `{{variable}}` substitution and may also contain wildcard characters (`*`, `?`, `[…]`). Only entries in the configured prefix whose names match the pattern are listed. With `--recursive`, matching directories are expanded into full trees.

Example: `yd-ls -R 'results_*'` lists all items matching `results_*`, showing directory contents as trees.

## yd-copy

The `yd-copy` command copies files or directories between remote data client locations. Both source and destination are remote paths; no local files are involved.

```
yd-copy [options] <src-path> <dst-path>
```

`<src-path>` and `<dst-path>` are paths relative to their respective configured `remote:bucket/prefix` base paths. Both support `{{variable}}` substitution.

Key options:
- `--dst-profile <name>` — use a named `[dataClient.<name>]` TOML profile for the destination (inherits unset fields from `[dataClient]`); defaults to the base `[dataClient]` config
- `--dst-prefix <prefix>` — override the destination path prefix; pass `''` to place files at the bucket root
- `--sync` — mirror the source to the destination, deleting destination files not present in the source
- `--recursive`/`-R` — accepted for explicitness; rclone copies recursively by default
- `--dry-run`/`-D` — show what would happen without performing any transfers

The source remote is configured via the standard data client flags (`--remote`, `--bucket`, `--prefix`, `--no-prefix`, `--data-client-profile`, or TOML `[dataClient]` settings).

Examples:

```bash
# Copy a file to a new location within the same prefix
yd-copy input/data.csv output/data.csv

# Rename a file while copying (destination path does not end with '/')
yd-copy results/output.csv archive/output-{{date}}.csv

# Copy a directory to a different prefix on the same remote
yd-copy --dst-prefix staging input/ input/

# Copy results to a named profile (e.g. a separate bucket defined in config.toml)
yd-copy --dst-profile production results/ results/

# Sync a directory to a backup profile (deletes destination files not in source)
yd-copy --sync --dst-profile backup data/ data/

# Copy from outside the configured prefix using --no-prefix
yd-copy --no-prefix shared/configs/base.json configs/base.json

# Dry-run to preview what would be copied without transferring anything
yd-copy --dry-run input/ output/
```

# Creating, Updating and Removing YellowDog Resources

The commands **yd-create** and **yd-remove** allow the creation, update and removal of the following YellowDog resources:

- Keyrings
- Credentials
- Compute Source Templates
- Compute Requirement Templates
- Image Families, Image Groups, and Images
- Namespaces
- Namespace Storage Configurations
- Configured Worker Pools
- Allowances
- String Attribute Definitions
- Numeric Attribute Definitions
- Namespace Policies
- Groups
- Applications
- Users (update only)

## Overview of Operation

The **yd-create** and **yd-remove** commands operate on a list of one or more resource specification files in JSON (or Jsonnet) format.

Each resource specification file can contain a single resource specification or a list of resource specifications. Different resource types can be mixed together in the same list.

The complete list of resource specifications is re-sequenced on processing to ensure that possibly dependent resources are dealt with in a suitable order. For example, all Compute Source Templates are always processed before any Compute Requirement Templates on resource creation, and the reverse sequencing is used on resource removal.

Resource specification files can use all forms of **variable substitution** just as in the case of Work Requirements, etc.

### Resource Creation

To create resources, use the `yd-create` command as follows:

```shell
yd-create resources_1.json <resources_2.json, ...>
```

### Resource Update

Resources are updated by re-running the `yd-create` command with the same (edited) resource specifications. Update operations will prompt the user for approval: as in other commands, this can be overridden using the `--yes` command line option.

The update action will create any resources that are not already present in the Platform, and it will update any resources that are already present. The command does not check for specific differences, so an unchanged resource specification will still cause an update.

### Resource Removal

Resources are removed by running the `yd-remove` command, with the same form of resource specifications. For example:

```shell
yd-remove resources_1.json <resources_2.json, ...>
```
Destructive operations will prompt the user for approval: as in other commands, this can be overridden using the `--yes` command line option.

The `yd-remove` command can also be used to remove resources by their `ydid` resource IDs, by using the `--ids` option. For example:

```shell
yd-remove --ids ydid:crt:D9C548:2a09093d-c74c-4bde-95d1-c576c6f03b13 ydid:imgfam:D9C548:4bc3cc57-1387-49a6-85d4-132bcf3a65fd
```

### Resource Matching

Resources match on **resource names** and (where applicable) **resource namespaces** rather than on YellowDog IDs. This is done for flexibility and to allow the `yd-create` and `yd-remove` commands to be stateless (i.e., we don't need to keep a local record of the YellowDog IDs of the resources created).

However, this means that **caution is required** when updating or removing resources, since resource matching is done using **only** the **namespace/name** of the resource -- i.e., the system-generated `ydid` IDs are not used. This means that a resource with a given name could have been removed and replaced in the platform by some other means, and the resource specification(s) would still match it.

## Resource Specification Definitions

The JSON specification used to define each type of resource can be found by inspecting the YellowDog Platform REST API documentation at https://docs.yellowdog.co/api.

For example, to obtain the JSON schema for creating a Compute Source Template, take a look at the REST API models for the Compute API: https://docs.yellowdog.ai/api?spec=Compute%20API.

When using the `yd-create` and `yd-remove` commands, note that an additional property `resource` must be supplied, to identify the type of resource being specified. The `"resource"` property can take the following values:

- `"Keyring"`
- `"Credential"`
- `"ComputeSourceTemplate"`
- `"ComputeRequirementTemplate"`
- `"MachineImageFamily"`
- `"ConfiguredWorkerPool"`
- `"Allowance"`
- `"StringAttributeDefinition"`
- `"NumericAttributeDefinition"`
- `"NamespacePolicy"`
- `"Group"`
- `"Application"`
- `"User"`

## Generating Resource Specifications using `yd-list`

To generate example JSON specifications from resources already included in the platform, the `yd-list` command can be used with the `--details`, `--substitute-ids`/`-U`, and  `--strip-ids` options, and select the resources for which details are required. E.g.:

```shell
yd-list compute-source-templates --details --substitute-ids --strip-ids
yd-list compute-requirement-templates --details --substitute-ids --strip-ids
yd-list image-families --details --substitute-ids --strip-ids
```

This will produce a list of resource specifications that can be copied and used directly with `yd-create` and `yd-remove`.

The detailed resource list can also be copied directly to an output file in addition to being displayed on the console using the `--output-file` option:

```shell
yd-list compute-source-templates --details --output-file my-resources.json
```

Alternatively, the `yd-show` command can be used with one or more `ydid` arguments to generate the details of each identified resource. E.g.,

```shell
yd-show -q ydid:cst:000000:cde265f8-0b17-4e0e-be1c-505174a620e4 --substitute-ids --strip-ids --output-file my-compute-source-template.json
```

would generate a JSON file that can be used with `yd-create` without alteration, or which could be edited.

As illustrated above, both `yd-list` and `yd-show` support the `--substitute-ids`/`-U` option. For Compute Requirement Template detailed output, this will substitute Compute Source Template IDs and Image Family and Group IDs with their names, to make it easier to reuse the outputs. For Compute Source Templates, Image Family and Group IDs will be substituted.

The `--strip-ids` option will remove any YellowDog IDs ('ydids') from the JSON output, as well as any other properties that are not required in order to use the output with `yd-create`.

### Usage Scenario: Moving or Copying Resources to a New Namespace

In the following usage scenario, we want to move a set of resources from one namespace `ns-1`, to another `ns-2`. We'll move all compute source templates, compute requirement templates, and image families.

**Step 1: Capture the target resources in JSON files**

```shell
yd-list compute-source-templates -q --namespace ns-1 --substitute-ids --strip-ids --auto-select-all --output-file csts.json
yd-list compute-requirement-templates -q --namespace ns-1 --substitute-ids --strip-ids --auto-select-all --output-file crts.json
yd-list image-families -q --namespace ns-1 --substitute-ids --strip-ids --auto-select-all --output-file ifs.json
```

**Step 2: Remove all target resources** if moving resources

The following will remove all target resources included in the JSON resource files **without user confirmation**. If one instead wants to **copy** the resources to the new namespace rather than move them, omit this step.

```shell
yd-remove -y csts.json crts.json ifs.json
```

**Step 3: Change the namespace in all the resources**

Use an editor's search and replace function, or a command line tool such as `sed` to replace all occurences of `"ns-1"` with `"ns-2`", for every `namespace` property, in each of the JSON files.

**Step 4: Recreate all resources in the new namespace**

```shell
yd-create -y csts.json crts.json ifs.json
```

Once the resources have been created successfully, the JSON files can be deleted (or retained for your records).


## Preprocessing Resource Specifications

The `--dry-run`/`-D` and `--jsonnet-dry-run`/`-J` options can be used with `yd-create` to display the processed JSON data structures without any resources being created or updated.

Below, we'll discuss each item type with example specifications.

## Keyrings

The Keyring models can be found in the Account API at: https://docs.yellowdog.ai/api?spec=Account%20API.

An example Keyring specification is shown below:

```json
{"resource": "Keyring", "name": "my-keyring-1", "description": "My First Keyring"}
```

or to specify two Keyrings at once:

```json
[
  {"resource": "Keyring", "name": "my-keyring-1", "description": "My First Keyring"},
  {"resource": "Keyring", "name": "my-keyring-2", "description": "My Second Keyring"}
]
```

When a new Keyring is created it's usable only by the YellowDog application which created it. A **system-generated password** is also returned as a one time response, which would allow the Keyring also to be claimed by YellowDog Portal users. For security reasons the password is not displayed, but this behaviour can be overridden using the `--show-keyring-passwords` command line option, e.g.:

```shell
% yd-create --quiet --show-keyring-passwords keyring.json
Keyring 'my-keyring-1': Password = 4OQAdcZagUX7ZiHaYvqC4yuKb4KCyN9lk4Z7mCcTYXA
```

Note that Keyrings **cannot be updated**; they must instead be removed and recreated, and in doing so, any contained credentials will be lost.

## Credentials

The Credential models can be found in the Account API at: https://docs.yellowdog.ai/api?spec=Account%20API.

For example, to add a single AWS credential to a Keyring, the following resource specification might be used:

```json
{
  "resource": "Credential",
  "keyringName": "my-keyring-1",
  "credential": {
    "type": "co.yellowdog.platform.account.credentials.AwsCredential",
    "name": "my-aws-creds",
    "description": "Fake AWS credentials",
    "accessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "secretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
  }
}
```
To **update** a Credential, make the modifications to the resource specification and run `yd-create` again, and to remove a credential, run `yd-remove`.

## Compute Source Templates

The Compute Source Template models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

An example Compute Source resource specification is found below:

```json
{
  "resource": "ComputeSourceTemplate",
  "namespace": "my-namespace",
  "description": "one",
  "attributes": [],
  "source": {
    "type": "co.yellowdog.platform.model.AwsInstancesComputeSource",
    "name": "my-compute-source-template",
    "credential": "my-keyring/my-aws-credential",
    "region": "eu-west-1",
    "availabilityZone": null,
    "securityGroupId": "sg-07bcbfb052873888",
    "instanceType": "*",
    "imageId": "*",
    "limit": 0,
    "specifyMinimum": false,
    "assignPublicIp": true,
    "createClusterPlacementGroup": null,
    "createElasticFabricAdapter": null,
    "enableDetailedMonitoring": null,
    "keyName": null,
    "iamRoleArn": null,
    "subnetId": "subnet-0d241e541249e9fdc",
    "userData": null,
    "instanceTags": {"environment": "demo-prod"}
  }
}
```

The `userData` property inside the `source` object accepts an inline script string. As an alternative, `userDataFile` accepts a path to a single script file, and `userDataFiles` accepts a list of paths whose contents are concatenated in order. These three properties are mutually exclusive. Relative paths are resolved from the directory containing the resource specification file. Variable substitutions using the `__variable__` syntax are applied to the file contents.

In the Compute Source Template `imageId` property, an Image Family name **namespace/family-name** or Image Group name **namespace/family-name/group-name** may be used instead of an ID. For example: `"imageId": "yellowdog/yd-agent-docker"`. The `yd-create` command will look up the Image Family name and substitute with a well-formed name or ID. A **`yd/`** prefix may also optionally be used.

## Compute Requirement Templates

The Compute Requirement Template models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

An example Compute Requirement resource specification is found below, for a **static** tempate:

```json
{
  "resource": "ComputeRequirementTemplate",
  "imagesId": "ami-097767a3a3e071555",
  "instanceTags": {},
  "name": "my-static-compute-template",
  "namespace": "my-namespace",
  "strategyType": "co.yellowdog.platform.model.WaterfallProvisionStrategy",
  "type": "co.yellowdog.platform.model.ComputeRequirementStaticTemplate",
  "sources": [
    {"instanceType": "t3a.small", "sourceTemplateId": "ydid:cst:D9C548:d41c36a7-0630-4fa2-87e7-4e20bf472bcd"},
    {"instanceType": "t3a.medium", "sourceTemplateId": "ydid:cst:D9C548:d41c36a7-0630-4fa2-87e7-4e20bf472bcd"}
  ]
}
```

Note that Compute Source Template **namespace/names** in the form `namespace/compute_source_template_name` can be used instead of their IDs: the **yd-create** command will look up the IDs and make the substitutions. The Compute Source Templates must already exist.

The top-level `userData` property accepts an inline script string. As with Compute Source Templates, `userDataFile` and `userDataFiles` are also supported as mutually exclusive alternatives (see above).

Also, In the `imagesId` property, an Image Family name **namespace/family-name** or an Image Group name **namespace/family-name/group-name** may be used instead of an ID. For example: `"imagesId": "yellowdog/yd-agent-docker/latest"`. The `yd-create` command will look up the Image Family name and substitute with a well-formed name or ID. A **`yd/`** prefix may also optionally be used.

A **dynamic** template example is:

```json
{
  "resource": "ComputeRequirementTemplate",
  "sourceTraits": {},
  "strategyType": "co.yellowdog.platform.model.SplitProvisionStrategy",
  "type": "co.yellowdog.platform.model.ComputeRequirementDynamicTemplate",
  "imagesId": "ydid:imgfam:000000:41962592-577c-4fde-ab03-d852465e7f8b",
  "instanceTags": {},
  "maximumSourceCount": 10,
  "minimumSourceCount": 1,
  "name": "my-dynamic-compute-template",
  "namespace": "my-namespace",
  "constraints": [
    {
      "anyOf": ["AWS"],
      "attribute": "source.provider",
      "type": "co.yellowdog.platform.model.StringAttributeConstraint"
    },
    {"attribute": "yd.cost", "max": 0.05, "min": 0, "type": "co.yellowdog.platform.model.NumericAttributeConstraint"},
    {
      "anyOf": ["UK", "Ireland"],
      "attribute": "yd.country",
      "type": "co.yellowdog.platform.model.StringAttributeConstraint"
    },
    {"attribute": "yd.ram", "max": 4096, "min": 2, "type": "co.yellowdog.platform.model.NumericAttributeConstraint"}
  ],
  "preferences": [
    {
      "attribute": "yd.cpu",
      "rankOrder": "PREFER_HIGHER",
      "type": "co.yellowdog.platform.model.NumericAttributePreference",
      "weight": 3
    },
    {
      "attribute": "yd.ram",
      "rankOrder": "PREFER_HIGHER",
      "type": "co.yellowdog.platform.model.NumericAttributePreference",
      "weight": 2
    },
    {
      "attribute": "yd.cpu-type",
      "preferredValues": ["AMD"],
      "type": "co.yellowdog.platform.model.StringAttributePreference",
      "weight": 1
    }
  ]
}
```

## Image Families

The Image Family models can be found in the Image API: https://docs.yellowdog.ai/api?spec=Images%20API.

An example specification, illustrating a containment hierarchy of Image Family -> Image Group -> Image, is shown below:

```json
{
  "resource": "MachineImageFamily",
  "access": "PRIVATE",
  "metadataSpecification": {},
  "name": "my-windows-image-family",
  "namespace": "my-namespace",
  "osType": "WINDOWS",
  "imageGroups": [
    {
      "metadataSpecification": {},
      "name": "v5_0_16",
      "osType": "WINDOWS",
      "images": [
        {
          "metadata": {},
          "name": "win-2022-yd-agent-5_0_16",
          "osType": "WINDOWS",
          "provider": "AWS",
          "providerImageId": "ami-0cb09e7f49c1eb021",
          "regions": ["eu-west-1"],
          "supportedInstanceTypes": []
        },
        {
          "metadata": {},
          "name": "win-2022-yd-agent-5_0_16",
          "osType": "WINDOWS",
          "provider": "AWS",
          "providerImageId": "ami-0cb09e7f49c1eb022",
          "regions": ["eu-west-2"],
          "supportedInstanceTypes": []
        }
      ]
    }
  ]
}
```

Note that if the name of an Image Group or an Image is changed in the resource specification, the existing resource with the previous name will be removed from the Platform because it's no longer present in the resource specification. To prevent this, retain the previous resource in your specification, and add resources as required.

## Configured Worker Pools

The Configured Worker Pool models can be found in the Scheduler API at: https://docs.yellowdog.ai/api?spec=Scheduler%20API.

Example:

```json
{
  "resource": "ConfiguredWorkerPool",
  "name": "my-configured-pool-pwt",
  "namespace": "my-namespace", 
  "properties": {
    "nodeConfiguration": {
      "nodeTypes": [
        {
          "name": "example",
          "count": 0,
          "min": 0,
          "sourceNames": ["example"],
          "slotNumbering": "REUSABLE"
        }
      ],
      "nodeEvents": {
        "STARTUP_NODES_ADDED": []
      },
      "targetNodeCount": 0
    }
  }
}
```

## Allowances

The Allowance models can be found in the Usage API at: https://docs.yellowdog.ai/api?spec=Usage%20API.

Example:
```json
{
  "resource": "Allowance",
  "description": "my-allowance",
  "allowedHours": 1000,
  "effectiveFrom": "Now",
  "effectiveUntil": "After two months",
  "instanceTypes": [],
  "limitEnforcement": "SOFT",
  "monitoredStatuses": ["RUNNING", "PENDING", "STOPPED", "TERMINATING", "STOPPING"],
  "regions": ["eu-west-2"],
  "resetType": "NONE",
  "sourceCreatedFromId": "awsondemand-eu-west-2",
  "type": "co.yellowdog.platform.model.SourcesAllowance"
}
```

The `effectiveFrom` and `effectiveUntil` date-time string fields can use any format supported by the **[dateparser](https://dateparser.readthedocs.io/en/latest/)** library, including some natural language formulations.

Compute Source Template and Compute Requirement Template IDs can use names instead of IDs, and the IDs will be substituted by `yd-create`. However, if a Source allowance is created (type `co.yellowdog.platform.model.SourceAllowance`), then the Compute Source ID (note: **not** the Compute Source Template ID) itself must be used in the `sourceId` property.

Allowances **cannot be updated** (edited) once they have been created; they can only be removed and recreated. However, if using `yd-create` to update existing Allowances, the `--match-allowances-by-description`/`-M` option can be used, in which case Allowances will be matched using their `description` property. If matches are found, these can optionally be removed before new Allowances are created. If multiple existing, matching Allowances are found, the user will be asked to select which ones (if any) to remove.

When using `yd-remove`, Allowances are again matched using their `description` property only if `--match-allowances-by-description`/`-M` is used. As with other resources, Allowances can also be removed by their IDs (`yd-remove --ids <allowance_id> [<allowance_id>]`).

Allowances can be **boosted** (have extra hours added to the Allowance) using the `yd-boost` command.

## Attribute Definitions

The Attribute Definition models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

### String Attribute Definitions

Example:

```json
{
  "resource": "StringAttributeDefinition",
  "name": "user.my-attribute",
  "title": "My attribute title",
  "description": "This is a description of my attribute",
  "options": ["yes", "no", "maybe"]
}
```

The `name` and `title` properties are required, while the rest are optional. The `user.` prefix is required when specifying the `name` property.

### Numeric Attribute Definitions

Example:

```json
{
  "resource": "NumericAttributeDefinition",
  "name": "user.my-numeric-attribute",
  "title": "Attribute Title",
  "defaultRankOrder": "PREFER_LOWER",
  "description": "A description of the attribute",
  "units": "$",
  "range": {"min": 1, "max": 10}
}
```

The `name`, `title` and `defaultRankOrder` properties are required, while the rest are optional. Either the `range` property or the `options` property (with numeric option values) can be specified, but not both. The `user.` prefix is required when specifying the `name` property.

## Namespace Policies

Example:

```json
{
  "resource": "NamespacePolicy",
  "namespace": "test_namespace",
  "autoscalingMaxNodes": 3
}
```

Namespace Policies are matched by their `namespace` property when using `yd-create` and `yd-remove`. The `autoscalingMaxNodes` property can be omitted or set to `null` to remove an existing limit for a namespace.

## Groups

When creating and updating groups, a list of roles with their scopes can can be supplied and the group will be created or updated with the roles specified. Roles can be identified by their names or YellowDog IDs.

Example:

```json
{
  "resource": "Group",
  "name": "my-group",
  "description": "Description of my group",
  "roles": [
    {
      "role": {"name": "work-viewer"},
      "scope": {"global": true}
    },
    {
      "role": {"name": "work-manager"},
      "scope": {
        "global": false,
        "namespaces": [
          {"namespace": "namespace-1"},
          {"namespace": "namespace-2"}
        ]
      }
    }
  ]
}
```

## Applications

When creating and updating Applications, a list of groups to which the Application should belong can optionally be supplied. Groups can be specified by their names or YellowDog IDs.

Example:

```json
{
    "resource": "Application",
    "name": "my-app",
    "description": "Description of my app",
    "groups" : ["administrators"]
}
```

### Granting Keyring Access

An optional `keyrings` list can be supplied to grant the Application access to one or more Keyrings. Keyring names are used to identify the Keyrings.

```json
{
    "resource": "Application",
    "name": "my-app",
    "keyrings": ["my-keyring-1", "my-keyring-2"]
}
```

When an Application is **created**, the full API key returned at creation time is used to perform the grant — no additional options are required.

When an Application is **updated**, the grant is attempted without an API key secret. If the platform requires the key secret (e.g., for initial access setup), re-run the update with `--regenerate-app-keys`; the newly generated key will be used to perform the grant.

### Creating and Regenerating Application Keys

When an Application is created, its Application Key ID and Secret will be displayed (even if the `--quiet` option is used).

When an Application is updated, the `--regenerate-app-keys` option can be used. This will invalidate the current Application key and secret, revoke any Keyring access, and generate a new key and secret which will be displayed.

## Users

Users cannot be created or removed using the resource specification approach, but their groups can be managed. Groups can be specified by their names or YellowDog IDs.

Users can be identified as follows:

**Internal** YellowDog users can be identified by their `username`, `name`, or `id` properties:

```json
{
  "resource": "InternalUser",
  "username": "my-username",
  "groups": ["administrators", "test"]
}
```

**External** users (users authenticated by an external auth provider) can be identified by their `name` or `id` properties:


```json
{
  "resource": "ExternalUser",
  "name": "Firstname Lastname",
  "groups": ["administrators", "test"]
}
```

When specified by the YellowDog ID:

```json
{
  "resource": "InternalUser",
  "id": "ydid:user:000000:73c3189e-4e87-4e32-bdbd-8b45e7e9780c",
  "groups": ["administrators", "test"]
}
```

## Namespaces

Namespaces can be created and removed using specifications of the form:

```json
{
  "resource": "Namespace",
  "name": "my-namespace"
}
```

Note that namespaces cannot currently be removed if they have been populated at any point.

# Jsonnet Support

In all circumstances where JSON files are used by the YellowDog CLI commands, **[Jsonnet](https://jsonnet.org)** files can be used instead. This allows the use of Jsonnet's powerful JSON extensions, including comments, variables, functions, etc.

A simple usage example might be:

```shell
yd-submit my_work_req.jsonnet
```

The use of the filename extension `.jsonnet` will activate Jsonnet evaluation. (Note that a temporary JSON file is created as part of Jsonnet processing, which you may see referred to in error messages: this file will have been deleted before the command exits.)

## Jsonnet Installation

Jsonnet is **not** installed by default. If you try to use a Jsonnet file without it installed, the commands will print an error with installation instructions.

**With pipx:**

```shell
pipx inject yellowdog-cli jsonnet
```

To update Jsonnet alongside the CLI:

```shell
pipx upgrade yellowdog-cli
pipx inject --force yellowdog-cli jsonnet
```

**With uv:**

```shell
uv tool install "yellowdog-cli[jsonnet]"
```

To update:

```shell
uv tool upgrade yellowdog-cli
```

**With pip:**

```shell
pip install -U "yellowdog-cli[jsonnet]"
```

## Variable Substitutions in Jsonnet Files

The scripts provide full support for variable substitutions in Jsonnet files, using the same rules as for the JSON specifications. Remember that for **Worker Pool** and **Compute Requirement** specifications, variable substitutions must be prefixed and postfixed by double underscores (`__`), e.g. `"__{{username}}__"`.

Variable substitution is performed before Jsonnet expansion into JSON, **and** again after the expansion.

## Checking Jsonnet Processing

There are three possibilities for verifying that a Jsonnet specification is doing what is intended:

1. To inspect the basic conversion of Jsonnet into JSON, without any additional processing by the YellowDog CLI commands, the `yd-jsonnet2json` command can be used. This takes the name(s) of the Jsonnet file(s) to be processed:

```shell
yd-jsonnet2json my_file.jsonnet
```


2. The `jsonnet-dry-run` (`-J`) option of the `yd-submit`, `yd-provision`, `yd-instantiate`, `yd-create` and `yd-remove` commands will generate JSON output representing the Jsonnet to JSON processing only, including applicable variable substitutions, but before full property expansion into the JSON that will be submitted to the Platform.


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

When this is inspected using the `jsonnet-dry-run` option (`yd-submit -Jq my_work_req.jsonnet`), this is the processed output:

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

When this is inspected using the `dry-run` option (`yd-submit -D my_work_req.jsonnet`), this is the processed output:

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

# Command List

Help is available for all commands by invoking a command with the `--help` or `-h` option. Some command line parameters are common to all commands, while others are command-specific.

All destructive commands require user confirmation before taking effect. This can be suppressed using the `--yes` or `-y` option, in which case the command will proceed without confirmation.

Some commands support the `--interactive` or `-i` option, allowing user selections to be made. E.g., this can be used to select which object paths to delete.

The `--quiet` or `-q` option reduces the command output down to essential messages only. For `yd-submit`, `yd-provision`, and `yd-instantiate`, `--quiet` prints **only the YDID** of the created entity to stdout, making those commands directly composable in shell scripts:

```bash
WR_ID=$(yd-submit --quiet)
yd-follow "$WR_ID"
```

The `--print-pid` (or `--pp`) option prefixes every log line with the process ID of the CLI invocation. This is useful when running multiple commands in parallel, to disambiguate interleaved output.

If you encounter an error it can be useful for support purposes to see the full Python stack trace. This can be enabled by running the command using the `--debug` option.

To suppress output formatting, including coloured output and line wrapping, the `--no-format` option can be used. Note that any outputs exceeding 1,000 lines in size (e.g., a very large JSON object, or table), will not produce coloured output.

## yd-submit

The `yd-submit` command submits a new Work Requirement, according to the Work Requirement definition found in the `workRequirement` section of the TOML configuration file and/or the specification found in a Work Requirement JSON document supplied using the `--work-requirement` option.

Use the `--dry-run` option to inspect the details of the Work Requirement, Task Groups, and Tasks that will be submitted, in JSON format.

Once submitted, the Work Requirement will appear in the **Work** tab in the YellowDog Portal.

The Work Requirement's progress can be tracked to completion by using the `--follow` (or `-f`) option when invoking `yd-submit`: the command will report on Tasks as they conclude and won't return until the Work Requirement has finished.

For a compact, live view, use `--progress` instead. This displays a progress bar showing completed and failed tasks vs. the total, and blocks until the Work Requirement finishes — similar to `--follow` but with a single updating line rather than per-task event messages.

When `--quiet` (`-q`) is used, only the YDID of the submitted Work Requirement is printed to stdout, with all other output suppressed. This is convenient for scripting:

```bash
WR_ID=$(yd-submit --quiet)
yd-follow "$WR_ID"
```

To submit a Work Requirement in the `HELD` (paused) state, use `--hold` (`-H`); it can later be started with `yd-start`.

To submit a Work Requirement with no Task Groups (to be populated later), use `--empty` (`-e`). To add Task Groups or Tasks to an existing Work Requirement, use `--add-to` (`-A`). See [Adding Task Groups and Tasks to an Existing Work Requirement](#adding-task-groups-and-tasks-to-an-existing-work-requirement) for details.

To explicitly download or upgrade the rclone binary used by the Data Client, run `yd-submit --upgrade-rclone`.

## yd-provision

The `yd-provision` command provisions a new Worker Pool according to the specifications in the `workerPool` section of the TOML configuration file and/or in the specification found in a Worker Pool JSON document supplied using the `--worker-pool` option.

Use the `--dry-run` option to inspect the details of the Worker Pool specification that will be submitted, in JSON format.

The `--target <n>`/`-T <n>` option overrides the `targetInstanceCount` from the specification or configuration. (The same option is available for `yd-instantiate`.)

Once provisioned, the Worker Pool will appear in the **Workers** tab in the YellowDog Portal, and its associated Compute Requirement will appear in the **Compute** tab.

## yd-cancel

The `yd-cancel` command cancels any active Work Requirements, including any pending Task Groups and the Tasks they contain. 

The `namespace` and `tag` values in the `config.toml` file are used to identify which Work Requirements to cancel. Alternatively, specific Work Requirement names or YDIDs (or individual Task YDIDs) can be supplied as positional arguments.

By default, any Tasks that are currently running on Workers will continue to run to completion or until they fail. Tasks can be instructed to abort immediately by supplying the `--abort` or `-a` option to `yd-cancel`.

## yd-abort

The `yd-abort` command is used to abort Tasks that are currently running. The user interactively selects the Work Requirements to target, and then which Tasks within those Work Requirements to abort. The Work Requirements are not cancelled as part of this process.

Aborting a Task sends `SIGTERM` to the Task's subprocess, giving it an opportunity to clean up. The Task is then reported as `FAILED`. If the Task Type has an `abort` clause configured in the Agent's `application.yaml`, that script takes over abort handling entirely.

The `namespace` and `tag` values in the `config.toml` file are used to identify which Work Requirements to list for selection. Alternatively, targets can be supplied as positional arguments, each of which can be:

- a Task YDID, to abort that Task directly
- a Work Requirement name or YDID, to abort all executing Tasks within it
- a Task Group YDID, or `<wr-name>/<tg-name>`, to abort executing Tasks in a specific Task Group

With `--yes`/`-y`, all executing Tasks in all selected Work Requirements are aborted without prompting.

## yd-shutdown

The `yd-shutdown` command shuts down Worker Pools that match the `namespace` and `tag` found in the configuration file. All remaining work will be cancelled, but currently executing Tasks will be allowed to complete, after which the Compute Requirement will be terminated.

Specific Worker Pool names or YDIDs, and/or Node YDIDs (to shut down individual nodes), can optionally be supplied as positional arguments instead of using the `namespace`/`tag` selection.

The `--terminate`/`-T` option also immediately terminates the associated Compute Requirement(s) rather than waiting for executing Tasks to complete, and `--follow`/`-f` follows the shutdown to completion.

## yd-nodeaction

The `yd-nodeaction` command submits Node Actions to running Worker Pool nodes. Actions are defined in a JSON (or Jsonnet) spec file supplied via `--actions`. See the [Node Actions](#node-actions) section for a full description of the spec format, action types, and field reference.

```shell
# Submit actions to interactively selected node(s)
yd-nodeaction --actions my_actions.json --worker-pool my-pool

# Submit to all current nodes in a pool
yd-nodeaction --actions my_actions.json --worker-pool my-pool --all-nodes

# Submit to a specific node by YDID (worker pool resolved automatically)
yd-nodeaction --actions my_actions.json --node ydid:node:D9C548:...

# Submit to a specific node and follow progress until complete
yd-nodeaction --actions my_actions.json --node ydid:node:D9C548:... --follow

# Check node action queue status (interactive pool + node selection)
yd-nodeaction --status --worker-pool my-pool

# Check queue status for a specific node directly
yd-nodeaction --status --node ydid:node:D9C548:...

# Full JSON queue details for a specific node
yd-nodeaction --status --node ydid:node:D9C548:... --details
```

`--worker-pool` accepts a pool name or a Worker Pool YDID. If omitted, an interactive selection is shown. When `--node` is given with a node YDID, the Worker Pool is resolved automatically.

Use `--yes` (`-y`) to skip the confirmation prompt.

## yd-instantiate

The `yd-instantiate` command instantiates a Compute Requirement (i.e., a set of instances that are managed by their creator and do not automatically become part of a YellowDog Worker Pool).

This command uses the data from the `workerPool` configuration section (or, synonymously, the `computeRequirement` section), but only uses the `name`, `templateId`, `targetInstanceCount`, `instanceTags`, `userData`, `requirementTag`, and `imagesId` properties. In addition, the Boolean property `maintainInstanceCount` (default = `false`) is available for use with `yd-instantiate`.

Compute Requirements can be instantiated directly from JSON (or Jsonnet) specifications, using the `--compute-requirement` (or `-C`) command line option, followed by the filename, or by using the `computeRequirementData` property in the `workerPool`/`computeRequirement` section. The properties listed above will be inherited from the config.toml `workerPool` specification if they are not present in the JSON file.

Variable substitutions must be prefixed and postfixed by a double underscore (`__`), e.g.: `"__{{my_variable}}__"`.

An example JSON specification is shown below:

```json
{
  "imagesId": "ydid:imgfam:000000:41962592-577c-4fde-ab03-d852465e7f8b",
  "instanceTags": {"a1": "one", "a2": "two"},
  "requirementName": "cr_test___{{datetime}}__",
  "requirementNamespace": "pyexamples",
  "requirementTag": "pyexamples-test",
  "templateId": "ydid:crt:000000:230e9a42-97db-4d69-aa91-29ff309951b4",
  "userData": "#/bin/bash\n#Other stuff...",
  "targetInstanceCount": 1,
  "maintainInstanceCount": true
}
```

Note that the `templateId` property can use either the YellowDog ID ('YDID') for the Compute Requirement Template, or its name. The same is true for the `imagesId` property.

If a Worker Pool is defined in JSON, using `workerPoolData` in the configuration file or by supplying the command line positional argument, `yd-instantiate` will extract the Compute Requirement from the Worker Pool specification (ignoring Worker-Pool-specific data), and use that for instantiating the Compute Requirement.

Use the `--dry-run` option to inspect the details of the Compute Requirement specification that will be submitted, in JSON format. The JSON output of this command can itself be used with the `yd-instantiate` command.

### Test-Running a Dynamic Template

When a the `templateId` of a Dynamic Requirement is used, the `yd-instantiate` command can be used to report on a test run of the Template, using the `--report` (or `-r`) command line option. This can be used with TOML-defined Compute Requirement specifications, but not those that are JSON-defined.

No instances will be provisioned during the test run.

For example:

```shell
% yd-instantiate --report --quiet
┌────┬────────┬────────────┬───────────────────────────┬───────────┬────────────────┬───────────────────┐
│    │   Rank │ Provider   │ Type                      │ Region    │ InstanceType   │ Source Name       │
├────┼────────┼────────────┼───────────────────────────┼───────────┼────────────────┼───────────────────┤
│  1 │      1 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.micro      │ awsspot-eu-west-2 │
│  2 │      2 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.small      │ awsspot-eu-west-2 │
│  3 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ c5a.large      │ awsspot-eu-west-2 │
│  4 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ c6a.large      │ awsspot-eu-west-2 │
│  5 │      3 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.medium     │ awsspot-eu-west-2 │
│  6 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m5a.large      │ awsspot-eu-west-2 │
│  7 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m5ad.large     │ awsspot-eu-west-2 │
│  8 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ m6a.large      │ awsspot-eu-west-2 │
│  9 │      4 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ t3a.large      │ awsspot-eu-west-2 │
│ 10 │      5 │ AWS        │ AwsInstancesComputeSource │ eu-west-2 │ r5a.large      │ awsspot-eu-west-2 │
└────┴────────┴────────────┴───────────────────────────┴───────────┴────────────────┴───────────────────┘
```

## yd-terminate

The `yd-terminate` command immediately terminates Compute Requirements that match the `namespace` and `tag` found in the configuration file. Any executing Tasks will be terminated immediately, and the Worker Pool will be shut down. Compute Requirements in either `RUNNING` or `STOPPED` states can be terminated.

Specific targets can optionally be supplied as positional arguments instead of using the `namespace`/`tag` selection. Each target can be:

- a Compute Requirement name or YDID (the whole requirement is terminated)
- a single instance, in `<compute-requirement-ydid>.<instance-id>` form
- a Node YDID (the node's instance is terminated)

The `--follow`/`-f` option follows the affected Compute Requirements' event streams after the action is applied.

## yd-compute-stop

The `yd-compute-stop` command stops `RUNNING` Compute Requirements and Instances. Stopped Compute Requirements and Instances can subsequently be started again using `yd-compute-start`.

If no arguments are supplied, Compute Requirements that match the `namespace` and `tag` found in the configuration file are candidates for stopping. Alternatively, the command accepts a list of any of the following:

- Compute Requirement names or YDIDs, to stop whole Compute Requirements
- Instances in `<compute-requirement-ydid>.<instance-id>` form, to stop individual Instances
- Node YDIDs, to stop the Instances on which Worker Pool Nodes are running

Usage examples:

```shell
yd-compute-stop
yd-compute-stop my-compute-requirement
yd-compute-stop ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185
yd-compute-stop ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185.i-0a1b2c3d4e5f67890
yd-compute-stop ydid:node:D9C548:f9d5a10e-5b0e-4b76-b50f-d2bbac0a5cb8
```

The `--follow`/`-f` option follows the event stream(s) of the affected Compute Requirement(s).

## yd-compute-start

The `yd-compute-start` command starts `STOPPED` Compute Requirements and Instances. It accepts the same arguments as `yd-compute-stop`: if no arguments are supplied, `STOPPED` Compute Requirements that match the `namespace` and `tag` are candidates for starting; otherwise, supply a list of Compute Requirement names or YDIDs, Instances in `<compute-requirement-ydid>.<instance-id>` form, or Node YDIDs.

## yd-compute-restart

The `yd-compute-restart` command restarts (reboots) `RUNNING` Instances. Restarting applies to Instances only; whole Compute Requirements cannot be restarted.

Instances to restart are supplied as a list of Instances in `<compute-requirement-ydid>.<instance-id>` form and/or Node YDIDs.

## yd-list

The `yd-list` command is used to list various YellowDog items, using the `namespace` and `tag` properties (if applicable) to target the scope of what to list.

The entity type to list is supplied as a positional argument:

```shell
yd-list <entity-type> [options]
```

Valid entity types are:

| Entity Type | Synonym | Description |
|---|---|---|
| `allowances` | `A` | Allowances |
| `applications` | `B` | Applications |
| `attribute-definitions` | `D` | User compute attribute definitions |
| `compute-requirement-templates` | `C` | Compute Requirement Templates |
| `compute-requirements` | `R` | Compute Requirements |
| `compute-source-templates` | `S` | Compute Source Templates |
| `groups` | `G` | Groups |
| `image-families` | `I` | Machine Image Families, Groups, and Images |
| `instances` | `E` | Compute instances (interactive: select a Compute Requirement first) |
| `keyrings` | `K` | Keyrings |
| `namespace-policies` | `L` | Namespace Policies |
| `namespaces` | `M` | Namespaces |
| `nodes` | `N` | Worker Pool Nodes (interactive: select a Worker Pool first) |
| `permissions` | `X` | Permissions |
| `roles` | `O` | Roles |
| `task-groups` | `H` | Task Groups (interactive: select a Work Requirement first) |
| `tasks` | `T` | Tasks (interactive: select a Work Requirement and Task Group first) |
| `users` | `U` | Users |
| `work-requirements` | `W` | Work Requirements |
| `worker-pools` | `P` | Worker Pools |
| `workers` | `F` | Workers (interactive: select a Worker Pool first) |

Unambiguous prefix matching is supported — for example `yd-list work-r` resolves to `yd-list work-requirements`, and `yd-list key` resolves to `yd-list keyrings`. Single uppercase synonyms also work, e.g. `yd-list W` and `yd-list K`.

Please use `yd-list --help` to inspect the full list of options. Commonly used options include:

| Option | Description |
|---|---|
| `--details`/`-d` | Show the full JSON representation of selected objects; in some cases this drills into additional detail, e.g. `yd-list keyrings --details` allows inspection of the Credentials within the selected Keyrings |
| `--active-only`/`-l` | List only entities in a non-terminated state, where applicable (e.g. Work Requirements, Worker Pools) |
| `--status <status>` | Include only entities whose status matches (case-insensitive); repeatable to allow multiple statuses |
| `--ids-only`/`-D` | Print only the YellowDog IDs of the listed entities, one per line |
| `--json`/`-J` | Emit the listing as a plain JSON array of summary objects (mutually exclusive with `--ids-only`) |
| `--reverse` | List items in reverse-sorted name order |
| `--public-ips-only` | With `instances`, list public IP addresses only |

For convenience, `tag` is set to the empty string unless explicitly set on the command line; `namespace` falls back to the configured value as usual.

## yd-resize

The `yd-resize` command is used to resize Worker Pools, and also Compute Requirements when used with the `--compute-requirement`/`-C` option. See `yd-resize --help` for more information.

The name or ID of the Worker Pool or Compute Requirement is supplied along with the new target number of Nodes or Instances. Usage examples:

```shell
yd-resize wp_pyex-slurm-pwt_230711-124356-0d6 10
yd-resize ydid:wrkrpool:D9C548:1f020696-ae9a-4786-bed2-c31b484b1d4f 10
yd-resize --compute-requirement cr_pyex-slurm-pwt_230712-110226-04c 5
yd-resize -C ydid:compreq:D9C548:600bef1f-7ccd-431c-afcc-b56208565aac 5
```

## yd-create

The `yd-create` command is used to create or update YellowDog resources, specified in one or more JSON (or Jsonnet) files supplied on the command line. Each file can contain one or more resources. See [Creating, Updating and Removing YellowDog Resources](#creating-updating-and-removing-yellowdog-resources) for the full resource specification reference.

## yd-remove

The `yd-remove` command is used to remove YellowDog resources, specified in one or more JSON (or Jsonnet) files supplied on the command line. Each file can contain one or more resources. See [Creating, Updating and Removing YellowDog Resources](#creating-updating-and-removing-yellowdog-resources) for details.

## yd-follow

The `yd-follow` command is used to follow the event streams for one or more Work Requirements, Worker Pools and Compute Requirements, specified by their YellowDog IDs (`ydids`), e.g.:

```shell
yd-follow ydid:workreq:D9C548:37d3c0cd-2651-4779-be17-89a8601b03b8 \
          ydid:wrkrpool:D9C548:c22f0d9a-4a99-460d-ae42-15653ba264c3 \
          ydid:compreq:D9C548:98879b5a-9192-4a56-ad25-fc1330e49185
```

The `yd-follow` command will continue to run until manually stopped using `CTRL-C`, unless all the IDs to be followed are in a terminal state.

Additional options:

- `--progress`: display a live progress bar for Work Requirement IDs (ignored for Worker Pool and Compute Requirement IDs)
- `--auto-follow-compute-requirements`/`-a`: automatically follow the associated Compute Requirements when following Worker Pools
- `--raw-events`: print the raw JSON event stream

## yd-wait

The `yd-wait` command waits for one or more Work Requirements, Worker Pools, or Compute Requirements to reach a terminal state, then exits with a status code reflecting the outcome:

- **Exit 0** — all entities concluded successfully
- **Exit 1** — one or more Work Requirements ended in a `FAILED` or `CANCELLED` state, or an error occurred fetching the final status

```shell
yd-wait ydid:workreq:D9C548:37d3c0cd-2651-4779-be17-89a8601b03b8
```

Multiple IDs can be supplied; `yd-wait` blocks until all of them have reached a terminal state. This makes it suitable for scripting pipelines:

```shell
WR_ID=$(yd-submit mywork.json --quiet)
yd-wait "$WR_ID" && yd-download results/
```

Use `--quiet` / `-q` to suppress all output and rely solely on the exit code, which is useful in automated pipelines. For interactive observation of event streams, use `yd-follow` instead.

## yd-start

The `yd-start` command is used to start `HELD` Work Requirements.

It can optionally be supplied with a list of the names and/or YDIDs of the specific Work Requirements to start, otherwise the `namespace` and `tag` will be used to generate a list of candidate requirements.

## yd-hold

The `yd-hold` command is used to hold (pause) `RUNNING` Work Requirements.

It can optionally be supplied with a list of the names and/or YDIDs of the specific Work Requirements to hold, otherwise the `namespace` and `tag` will be used to generate a list of candidate requirements.

## yd-boost

The `yd-boost` command adds hours to a YellowDog Allowance. Allowances are time-based compute budgets that limit how many CPU- or GPU-hours can be consumed by a namespace or application. Boosting is useful when a running job is approaching its limit and needs additional headroom.

The number of hours to add is supplied first, followed by the YDID(s) of one or more Allowances to boost (Allowance names are not accepted):

```shell
yd-boost 10 ydid:allowance:D9C548:...
yd-boost 10 ydid:allowance:D9C548:... ydid:allowance:D9C548:...
```

## yd-show

The `yd-show` command will show the details (in JSON) of any YellowDog entity that has a YellowDog ID. It supports IDs referring to:

- Compute Source Templates
- Compute Requirement Templates
- Compute Requirements
- Sources
- Worker Pools
- Nodes
- Workers
- Work Requirements
- Task Groups
- Tasks
- Image Families, Image Groups, and Images
- Keyrings
- Allowances
- Users
- Applications
- Groups
- Roles

When showing the details of a Configured Worker Pool, the `--show-token` option includes the Worker Pool token in the output.

The `--report-variable <var>`/`-r <var>` option reports the processed value of the specified variable substitution and exits; it can be supplied multiple times, or use `--report-variable all` to report all variables. Combine with `--quiet` to emit the report as JSON. This is useful for debugging variable substitution setups.

## yd-compare

The `yd-compare` command takes a Work Requirement or Task Group ID and one or more Worker Pool IDs, and compares the selected Task Group(s) against the available Nodes/Workers in the Worker Pool(s). If a Work Requirement ID is supplied, all Task Groups in the Work Requirement will be compared.

```commandline
yd-compare ydid:taskgrp:000000:83587010-5e26-4174-92a7-c7cc2612638d:1 ydid:wrkrpool:000000:3666e4c5-382e-4512-a2c7-33dbb839f75
```

The command checks if the **Run Specification** of a Task Group matches the properties of the Worker Pools and their registered Nodes and Workers, meaning there are Workers in the Worker Pool that could be claimed by the Task Group and that the Worker Pool would be a candidate for scaling up to meet the demands of the Task Group.

A detailed matching report showing the comparison against each specific property is created, which can be used to determine which properties are preventing a Worker Pool match.

The match status of a Worker Pool falls into one of four categories:

| **Match Status** | **Meaning**                                                                                                     |
|------------------|-----------------------------------------------------------------------------------------------------------------|
| **YES**          | The Worker Pool and every Node/Worker that has registered so far match the Task Group.                          |
| **NO**           | The Worker Pool and/or none of the Nodes/Workers that have registered so far match the Task Group.              |
| **MAYBE**        | The Worker Pool matches the Task Group but no Nodes have yet registered, so Node/Worker properties are unknown. |
| **PARTIAL**      | The Worker Pool and some of the Nodes/Workers that have registered are a match for the Task Group.              |

## yd-finish

The `yd-finish` command moves work requirements into the `FINISHING` state, meaning the requirements will be allowed to conclude but that no new tasks can be added.

## yd-application

The `yd-application` command shows the details of the current Application, i.e., the Application represented by the `key` and `secret` being used.

## yd-help

The `yd-help` command lists all available `yd-*` commands and their purposes:

```shell
yd-help
```

## yd-jsonnet2json

The `yd-jsonnet2json` command converts Jsonnet files to JSON without any additional processing by the CLI (no variable substitution, no property expansion). With a single (non-glob) argument, the resulting JSON is written to stdout; with multiple arguments or a glob pattern, each file is converted and written to a `<name>.json` file alongside its source:

```shell
yd-jsonnet2json my_spec.jsonnet            # JSON to stdout
yd-jsonnet2json spec_1.jsonnet spec_2.jsonnet   # writes spec_1.json, spec_2.json
yd-jsonnet2json 'specs/*.jsonnet'          # writes a .json file per match
```

This is the quickest way to verify that a Jsonnet file is syntactically correct and produces the expected JSON structure. For full variable substitution and property expansion, use `--jsonnet-dry-run` or `--dry-run` on the relevant command instead.

## yd-format-json

The `yd-format-json` command reformats JSON files in place using the CLI's compact JSON encoder (small containers on a single line, larger ones indented). Non-JSON files are ignored:

```shell
yd-format-json my_file.json my_other_file.json
```

## yd-version

The `yd-version` command reports the versions of the CLI, the YellowDog SDK, Python, and (if installed) Jsonnet. Each of the mutually exclusive options `--cli`, `--sdk`, `--python` and `--jsonnet` prints just that bare version number, for use in scripts:

```shell
yd-version           # report all versions
yd-version --cli     # print the CLI version number only
```

Neither `yd-version`, `yd-format-json`, `yd-help` nor `yd-jsonnet2json` requires a configuration file or YellowDog credentials.

## yd-copy

The `yd-copy` command copies files or directories between remote data client locations. See [Data Client](#data-client) for full documentation.

## yd-delete / yd-rm

The `yd-delete` command (synonym: `yd-rm`) deletes files or directories from a remote data store. See [Data Client](#data-client) for full documentation.

## yd-download

The `yd-download` command downloads files from a remote data store to the local filesystem. See [Data Client](#data-client) for full documentation.

## yd-ls

The `yd-ls` command lists files and directories in a remote data store. See [Data Client](#data-client) for full documentation.

## yd-upload

The `yd-upload` command uploads local files or directories to a remote data store. See [Data Client](#data-client) for full documentation.
