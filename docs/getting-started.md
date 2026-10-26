# Getting Started

<!--ts-->
   * [Before You Start](#before-you-start)
   * [1. Write a Configuration File](#1-write-a-configuration-file)
   * [2. Check It](#2-check-it)
   * [3. Describe the Work and the Workers](#3-describe-the-work-and-the-workers)
   * [4. Provision the Worker Pool](#4-provision-the-worker-pool)
   * [5. Submit the Work Requirement and Follow It](#5-submit-the-work-requirement-and-follow-it)
   * [6. See What Happened](#6-see-what-happened)
   * [7. Clean Up](#7-clean-up)
   * [Next Steps](#next-steps)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Oct 26 09:44:38 GMT 2026 -->

<!--te-->

This page takes you from an installed CLI to a first Work Requirement run on the YellowDog Platform: a configuration file, a check that it works, one Worker Pool, and one Task that prints a line. Every step is a single command, and each links to where it is described in full.

## Before You Start

You will need:

- **The CLI installed**, as described in the [README](../README.md#installation).
- **A YellowDog Platform account and an Application**, created in the [YellowDog Portal](https://portal.yellowdog.co/#/account/applications), with its **Key ID** and **Key Secret** to hand. The Application must belong to a group allowed to submit Work Requirements and provision Worker Pools in the namespace you will use; the `administrators` group may do everything.
- **A Compute Requirement Template** to provision instances from. If your account has none yet, the [Cloud Wizard](../README_CLOUDWIZARD.md) creates example templates in your AWS, Azure or Google Cloud account, such as `cloudwizard-aws/cloudwizard-aws-split-ondemand`.
- **An image with the YellowDog Agent installed**, for the instances to boot: an Image Family, or a cloud provider's image ID. The [YellowDog documentation](https://docs.yellowdog.ai) describes the images available and how to build your own.

## 1. Write a Configuration File

In an empty directory, run [`yd init`](commands.md#yd-init):

```shell
mkdir first-run && cd first-run
yd init
```

It asks for the Application's key ID and secret (the secret is typed unseen), a namespace, a tag and the Platform's URL, offering the value of `YD_KEY`, `YD_SECRET` and the others where they are set; press Enter at the URL to keep the default. It writes them to `config.toml`, readable by you alone since it holds the secret:

```toml
# YellowDog CLI configuration, written by 'yd init'. Every property, in this
# section and the others, is described in the Configuration page of the
# documentation ('yd --docs' prints the link). Run 'yd doctor' to check it.

[common]
key = "<your-key-id>"
secret = "<your-key-secret>"
namespace = "getting-started"
tag = "first-run"
# url = "https://api.yellowdog.ai"
```

The namespace holds what you create, and the tag names it: the Work Requirement and Worker Pool below are named after it, and the commands that act on many objects at once select by it. See [Configuration](configuration.md) for everything `config.toml` can hold.

## 2. Check It

Run [`yd doctor`](commands.md#yd-doctor):

```shell
yd doctor
```

It checks the installation, reads the configuration file, and then contacts the Platform: whether it can be reached, whether the key and secret are accepted (naming the Application), and whether the namespace can be read. Every row should be `OK`, or `SKIP` for a check that does not apply; a `FAIL` comes with what to do about it. Running it again after each change is the quickest way to know the change took.

## 3. Describe the Work and the Workers

Add two sections to `config.toml`, replacing the template and image with your own:

```toml
[workRequirement]
taskType = "bash"
arguments = ["-c", "echo Hello from $(hostname)"]
workerTags = ["{{tag}}"]

[workerPool]
templateId = "cloudwizard-aws/cloudwizard-aws-split-ondemand"
imagesId = "<namespace>/<image-family>"
targetInstanceCount = 1
workerTag = "{{tag}}"
```

The `[workRequirement]` section is a Work Requirement of one Task Group holding one Task, which runs `bash -c 'echo Hello from $(hostname)'` on a Worker. Its `taskType` must be one the Agent on the instances is configured to run. The `[workerPool]` section is a Worker Pool of one instance, booted from the template and image named. The Worker Pool's Workers carry the tag as their Worker Tag, and the Task Group asks for Workers with that tag (`{{tag}}` stands for the tag in `[common]`; see [Variable Substitutions](variables.md)), so this Work Requirement runs on this Worker Pool and no other.

To see what would be submitted without submitting it, use `--dry-run`:

```shell
yd workrequirement submit --dry-run
```

It prints the Work Requirement as JSON, its name generated from the tag (`first-run_261026-0943070-9s`). [Work Requirements](work-requirements.md) and [Worker Pools](worker-pools.md) describe every property these sections take, and how to write a Work Requirement with many Tasks as a JSON specification instead.

## 4. Provision the Worker Pool

```shell
yd workerpool provision
```

The command returns as soon as the Platform has accepted the Worker Pool. Its instance then takes a few minutes to boot and register its Workers; [`yd workerpool list`](commands.md#yd-list) shows the pool's status as it goes.

## 5. Submit the Work Requirement and Follow It

```shell
WR_ID=$(yd workrequirement submit --quiet)
yd workrequirement follow "$WR_ID"
```

With `--quiet`, `yd workrequirement submit` prints the new Work Requirement's YellowDog ID and nothing else, so the shell can keep it. `yd workrequirement follow` prints the Work Requirement's events as they happen and returns when it has finished, `COMPLETED` once the Task has run. The Task waits until a Worker is ready, so nothing runs until the instance has booted. `yd workrequirement submit --follow` does both in one command.

## 6. See What Happened

```shell
yd task list --within "$WR_ID"
yd task list --within "$WR_ID" --details
```

The first lists the Work Requirement's Tasks and their statuses, and `--details` adds each Task in full as JSON. A Task's console output is written to `taskoutput.txt` on the node, which is deleted with the Task's directory when it finishes; to keep it, upload it as one of the Task's outputs (see [Specifying Data Client Outputs](work-requirements.md#specifying-data-client-outputs)). The YellowDog Portal shows the Work Requirement, its Tasks and the Worker Pool too.

## 7. Clean Up

The Worker Pool shuts itself down when it has been idle long enough: an idle node after `idleNodeTimeout` (5 minutes by default), the whole pool after `idlePoolTimeout` (30 minutes). To shut it down at once:

```shell
yd workerpool shutdown
```

It lists the Worker Pools in the namespace whose names include the tag, and asks before shutting them down.

## Next Steps

- [Work Requirements](work-requirements.md): Task Groups and many Tasks, inheritance, CSV data, retries, and data inputs and outputs.
- [Worker Pools](worker-pools.md): sizing, idle timeouts, User Data and Node Actions.
- [Variable Substitutions](variables.md): parameterising specifications from the command line and the environment.
- [Data Client](data-client.md): moving files to and from object storage with `yd data`.
- [Command List](commands.md): every command, verb and option.
- [Machine-readable Output and Exit Codes](json-output.md): scripting with `--json`.
