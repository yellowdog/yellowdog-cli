# Why Isn't My Work Running?

<!--ts-->
   * [1. Is the Work Requirement Running?](#1-is-the-work-requirement-running)
   * [2. What Are Its Task Groups Waiting For?](#2-what-are-its-task-groups-waiting-for)
   * [3. Is There a Worker Pool?](#3-is-there-a-worker-pool)
         * [Details](#details)
   * [4. Does the Worker Pool Match?](#4-does-the-worker-pool-match)
      * [Comparing a Task Group with a Worker Pool](#comparing-a-task-group-with-a-worker-pool)
         * [Details](#details-1)
   * [5. Does the Worker Pool Have Nodes?](#5-does-the-worker-pool-have-nodes)
   * [6. Are the Tasks Failing?](#6-are-the-tasks-failing)
   * [If a Command Fails](#if-a-command-fails)
         * [What the Trace Shows](#what-the-trace-shows)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Wed Oct 28 12:01:53 GMT 2026 -->

<!--te-->

When a Work Requirement's Tasks don't start, work through the steps below in order. Each step names the command that shows what to check, and what to do about what it shows. [How a Task Finds a Worker](concepts.md) explains the matching these steps check.

The examples use a Work Requirement named `nightly-render` and a Worker Pool named `render-pool`. Names and YellowDog IDs work alike.

## 1. Is the Work Requirement Running?

```bash
yd workrequirement show nightly-render
```

Look at its `status`:

- **`RUNNING`**: go on to step 2.
- **`HELD`**: it runs no Tasks until it is started. Run `yd workrequirement start nightly-render`.
- **`FINISHING`**: it takes no new Tasks, and its remaining Tasks run to the end. Go on to step 2 if they aren't running.
- **`CANCELLING`**: it is being cancelled, and runs no new Tasks. Tasks already running carry on unless it was cancelled with `--abort`.
- **`COMPLETED`, `FAILED` or `CANCELLED`**: it has finished. To find out why Tasks failed, go to [step 6](#6-are-the-tasks-failing).

## 2. What Are Its Task Groups Waiting For?

```bash
yd taskgroup list --within nightly-render
```

Each Task Group's status is followed by what holds it up, if anything:

- **`/WAITING`**: it is waiting for a Task Group named in its `dependencies` to complete. Check that one instead.
- **`/STARVED`**: it can't claim any Workers. Go on to step 3.
- **`PENDING`** with nothing after it: it is waiting for the Workers it needs to run its Tasks, for example while a matching Worker Pool starts up. A Task Group submitted moments ago may show plain `PENDING` before it is flagged `/STARVED`, so check again after a minute. If it stays `PENDING`, go on to step 3.
- **`RUNNING`** with nothing after it: it has claimed Workers. If its Tasks still aren't completing, go to [step 6](#6-are-the-tasks-failing).

## 3. Is There a Worker Pool?

```bash
yd workerpool list --active-only --tag ''
```

A Task Group starves when no Worker Pool can serve it. If no pool is listed, or the one you expected is missing, provision one with `yd workerpool provision`. A Worker Pool shuts itself down after `idlePoolTimeout` (30 minutes by default) with no work, so a pool provisioned well before the Work Requirement may already have gone.

#### Details

**Pools the listing leaves out.** Without `--tag ''`, `yd workerpool list` shows only the pools in the configured namespace whose names include the configured tag, which leaves out a pool provisioned with another tag, or by a colleague. A pool in another namespace can serve the Task Group too, unless its `namespaces` leaves that namespace out: `--namespace ''` lists the pools in every namespace the Application can read.

## 4. Does the Worker Pool Match?

### Comparing a Task Group with a Worker Pool

```bash
yd workrequirement compare nightly-render render-pool
```

This compares each Task Group's run specification with the Worker Pool, property by property. For example, for a Task Group that uses the `docker` Task Type, and a pool whose Nodes have only the `bash` one:

```text
Comparing Task Group 'render' (ydid:taskgrp:000000:5f3c2d1e-8a7b-4c6d-9e0f-1a2b3c4d5e6f:1)
Detailed comparison report for NON-MATCHING (RUNNING) Worker Pool 'render-pool'
                      (ydid:wrkrpool:000000:3e1f9a2b-7c4d-4e5f-8a9b-0c1d2e3f4a5b)
    ┌──────────────────┬────────────────────────────────┬──────────────────┬────────────────┐
    │ Property         │ Task Group Run Specification   │ Worker Pool      │ Match Status   │
    ├──────────────────┼────────────────────────────────┼──────────────────┼────────────────┤
    │ Instance Pricing │                                │ ON_DEMAND_ONLY   │ YES            │
    │ Instance Type(s) │                                │ t3a.medium       │ YES            │
    │ Namespace(s)     │                                │ image-processing │ YES            │
    │ Provider(s)      │                                │ AWS              │ YES            │
    │ RAM (GB)         │                                │ 4.0              │ YES            │
    │ Region(s)        │                                │ eu-west-2        │ YES            │
    │ Task Type(s)     │ docker                         │ bash             │ NO             │
    │ vCPUs Count      │                                │ 2.0              │ YES            │
    │ Worker Tag(s)    │ render                         │ render           │ YES            │
    └──────────────────┴────────────────────────────────┴──────────────────┴────────────────┘
Task Group comparison complete
```

An empty cell in the Task Group's column means it sets no constraint there. Each `NO` row names something to change, on one side or the other:

| Row | To make it match |
|---|---|
| **Task Type(s)** | Add the Task Type to the Nodes' Agent, for example with `add-docker-task-type.sh` in the User Data (see [Where Task Types Come From](work-requirements.md#where-task-types-come-from)), or change the Tasks' `taskType` |
| **Worker Tag(s)** | Give the Worker Pool's `workerTag` and the Work Requirement's `workerTag` the same value |
| **Namespace(s)** | Provision the pool in one of the Task Group's `namespaces`, or add the pool's namespace to them |
| **Instance Pricing** | Provision from a template whose sources all provide the pricing the Task Group's `instancePricingPreference` asks for, or relax it to `SPOT_THEN_ON_DEMAND` or `ON_DEMAND_THEN_SPOT`, which only order the pools (see [Instance pricing](concepts.md#details)) |
| **Instance Type(s)**, **Provider(s)**, **Region(s)** | Widen the Task Group's `instanceTypes`, `providers` or `regions`, or provision from a template whose sources fit them |
| **RAM (GB)**, **vCPUs Count** | Widen the Task Group's `ram` or `vcpus` range, or use a larger or smaller instance type |

The CLI changes only a provisioned Worker Pool's size (`yd workerpool resize`), so a change on the pool's side means provisioning a new pool that matches. Shut the old one down (`yd workerpool shutdown render-pool`) once the new one is serving the work, and only if no other Work Requirement needs it. The CLI can't change a submitted Task Group's run specification, so a change on its side means cancelling the Work Requirement and submitting it again.

When every row is `YES`, the pool matches. If the Task Group still starves, its Nodes may not be up yet: go on to step 5.

#### Details

**`MAYBE`.** Task Types, RAM and vCPUs are compared with what the pool's Nodes report, so before any Node has registered they show `MAYBE (no Nodes available)`. A pool that has never had a Node scales up to one Node first, whose Task Types, RAM and vCPUs then decide whether the pool matches; if it doesn't, the Task Group stays starved. A pool that has had Nodes keeps what they reported, even after it has scaled down to none, and the Scheduler matches on that. `compare` has only the Node records the Platform lists, which are removed an hour after a Node terminates, so a pool that has scaled down to none shows `MAYBE` an hour later, whatever its earlier Nodes reported. Step 5 finds out why there are no Nodes.

**Several pools, one Task Group.** Give `yd workrequirement compare` several Worker Pools to compare each, with a summary table first. `yd taskgroup compare nightly-render/render render-pool` compares a single Task Group. The full table of what is compared is in [yd workrequirement compare](commands.md#yd-workrequirement-compare).

**Nodes still starting.** Every Node registered to the pool is compared, whatever its state. `--running-nodes-only` compares only the `RUNNING` ones.

## 5. Does the Worker Pool Have Nodes?

```bash
yd node list --within render-pool
```

The listing shows each Node's Task Types, Worker Tag and status. If it lists none:

- **The pool may still be starting.** Instances take a few minutes to boot, and a Node appears once its Agent registers. `yd workerpool follow render-pool` follows the pool's events as it starts.
- **An Allowance may be exhausted.** `yd workerpool show render-pool --show-exhaustion` lists any Allowances that are stopping the pool from getting instances. `yd allowance boost` raises one.
- **The instances may not be booting into the Agent.** An instance whose Agent hasn't registered within `nodeBootTimeout` (10 minutes by default) is terminated. Check that the image has the Agent installed, or that the User Data installs it (see [A First Run, with No Image of Your Own](worker-pools.md#a-first-run-with-no-image-of-your-own)). When the [Agent installer](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md) runs as User Data, its progress lines in an instance's console output start with `*** YD`, and a step that fails prints the end of its log, `/var/log/yd-agent-install.log`.
- **The cloud provider may be refusing the instances**, for example because the cloud credential is refused, the Application has no access to the Keyring holding it, or a quota in the cloud account has been reached. Look in `yd computerequirement show` for the pool's Compute Requirement (below): each of its `provisionStrategy`'s `sources` has a `status` and a `statusMessage`.
- **The cloud provider may have no capacity.** For a pool provisioned from a dynamic template, `yd workerpool show render-pool --show-source-report` shows which Compute Source Templates were chosen or rejected, and why.

To see the instances themselves, find the pool's `computeRequirementId` in `yd workerpool show render-pool`, and list them with `yd instance list --within <that ID>`.

If Nodes are listed, check that their Task Types and Worker Tag are the ones step 4 asked for.

## 6. Are the Tasks Failing?

If the Task Groups are running but the Work Requirement doesn't complete, look at the Tasks:

```bash
yd task list --within nightly-render --status failed
yd task list --within nightly-render --with-errors
```

`--with-errors` also lists the Tasks that hit an error and then completed on a retry. `yd task show nightly-render/render/task_01` shows a Task in full, its errors included; [Finding the Errors Your Tasks Hit](work-requirements.md#finding-the-errors-your-tasks-hit) describes what they mean.

`yd workrequirement follow nightly-render` reports the Work Requirement's progress as it happens.

## If a Command Fails

If a `yd` command itself fails, with an error about credentials, permissions or the connection, run `yd doctor`. It checks the installation, the configuration, the credentials and the connection to the Platform, and suggests a remedy for anything wrong.

To see what a command did before it failed, run it again with `--debug`. It writes a trace to stderr: the configuration it loaded, each request it made to the Platform with the response's status, and the stack trace of the failure. It leaves out the application key and secret.

```bash
yd workrequirement submit --debug 2> trace.txt
```

The trace also helps when a command succeeds but doesn't do what you expected, such as matching the wrong Work Requirement or reading the wrong file.

#### What the Trace Shows

Each line starts with the date and time, as the command's other messages do, then `DEBUG`, the seconds since the command started, in brackets, and the part of the CLI that wrote it (`dataclient.operations` for the `yd data` verbs' rclone runs):

```text
2026-10-28 14:48:21 : DEBUG : [+0.026s] load_config: Loading configuration data from: 'config.toml'
2026-10-28 14:48:21 : DEBUG : [+0.412s] named_targets: 'nightly-render' is ydid:workreq:000000:5f3c2d1e-8a7b-4c6d-9e0f-1a2b3c4d5e6f
2026-10-28 14:48:21 : DEBUG : [+0.415s] urllib3: https://api.yellowdog.ai:443 "GET /work/requirements/ydid:workreq:000000:5f3c2d1e-8a7b-4c6d-9e0f-1a2b3c4d5e6f HTTP/1.1" 200 2048
```

It shows:

- Where the configuration, the variable substitutions and the `.env` variables were loaded from, the Platform API URL and the HTTPS proxy in use.
- Each request to the Platform, with its response status.
- Each name resolved to its YellowDog ID, what each name pattern matched, and the namespaces searched when none was given.
- Each file read, by its full path, and the directory a specification's files were looked for in.
- For `yd workrequirement submit`, how the Tasks were batched and each failed attempt to add a batch; with `--add-to`, which Task Groups were already there and how the new Tasks were numbered.
- Each event stream opened, closed or reconnected, and the wait before reconnecting; after an action on a Compute Requirement, what `--follow` checked.
- What each target of an action, such as `cancel` or `terminate`, resolved to.
- The order `yd resource create` and `yd resource remove` work through their resources in.
- Each rclone command the `yd data` verbs run, and its exit status.
- What `yd workrequirement compare` read of each Worker Pool: its Compute Sources, its Nodes, and the Node whose Task Types stand for the pool's.
- The stack trace of a failure.

The trace never includes the application key or secret, a variable's value, or the parameters of an inline data client remote. `--quiet` and `--json` don't suppress it, and the command's exit code is the one it gives without `--debug`.
