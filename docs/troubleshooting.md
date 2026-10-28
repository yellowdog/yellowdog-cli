# Why Isn't My Work Running?

<!--ts-->
   * [1. Is the Work Requirement Running?](#1-is-the-work-requirement-running)
   * [2. What Are Its Task Groups Waiting For?](#2-what-are-its-task-groups-waiting-for)
   * [3. Is There a Worker Pool?](#3-is-there-a-worker-pool)
   * [4. Does the Worker Pool Match?](#4-does-the-worker-pool-match)
      * [Comparing a Task Group with a Worker Pool](#comparing-a-task-group-with-a-worker-pool)
         * [Details](#details)
   * [5. Has the Worker Pool Got Nodes?](#5-has-the-worker-pool-got-nodes)
   * [6. Are the Tasks Failing?](#6-are-the-tasks-failing)
   * [If a Command Fails](#if-a-command-fails)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Wed Oct 28 08:25:45 GMT 2026 -->

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
- **`COMPLETED`, `FAILED` or `CANCELLED`**: it has finished. To find out why Tasks failed, go to [step 6](#6-are-the-tasks-failing).

## 2. What Are Its Task Groups Waiting For?

```bash
yd taskgroup list --within nightly-render
```

Each Task Group's status is followed by what holds it up, if anything:

- **`/WAITING`**: it is waiting for a Task Group named in its `dependencies` to complete. Check that one instead.
- **`/STARVED`**: it can't claim any Workers. Go on to step 3.
- **`RUNNING`** with nothing after it: it has claimed Workers. If its Tasks still aren't completing, go to [step 6](#6-are-the-tasks-failing).

## 3. Is There a Worker Pool?

```bash
yd workerpool list --active-only
```

A Task Group starves when no Worker Pool can serve it. If no pool is listed, or the one you expected is missing, provision one with `yd workerpool provision`. A Worker Pool shuts itself down after `idlePoolTimeout` (30 minutes by default) with no work, so a pool provisioned well before the Work Requirement may already have gone.

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
| **Instance Type(s)**, **Provider(s)**, **Region(s)** | Widen the Task Group's `instanceTypes`, `providers` or `regions`, or provision from a template whose sources fit them |
| **RAM (GB)**, **vCPUs Count** | Widen the Task Group's `ram` or `vcpus` range, or use a larger or smaller instance type |

The CLI changes only a provisioned Worker Pool's size (`yd workerpool resize`), so a change on the pool's side means shutting it down (`yd workerpool shutdown render-pool`) and provisioning another. The CLI can't change a submitted Task Group's run specification, so a change on its side means cancelling the Work Requirement and submitting it again.

When every row is `YES`, the pool matches. If the Task Group still starves, its Nodes may not be up yet: go on to step 5.

#### Details

**`MAYBE`.** Task Types, RAM and vCPUs are compared with what the pool's Nodes report, so before any Node has registered they show `MAYBE (no Nodes available)`. Step 5 finds out why there are no Nodes.

**Several pools, one Task Group.** Give `yd workrequirement compare` several Worker Pools to compare each, with a summary table first. `yd taskgroup compare nightly-render/render render-pool` compares a single Task Group. The full table of what is compared is in [yd workrequirement compare](commands.md#yd-workrequirement-compare).

**Nodes still starting.** Every Node registered to the pool is compared, whatever its state. `--running-nodes-only` compares only the `RUNNING` ones.

## 5. Has the Worker Pool Got Nodes?

```bash
yd node list --within render-pool
```

The listing shows each Node's Task Types, Worker Tag and status. If it lists none:

- **The pool may still be starting.** Instances take a few minutes to boot, and a Node appears once its Agent registers. `yd workerpool follow render-pool` follows the pool's events as it starts.
- **An Allowance may be exhausted.** `yd workerpool show render-pool --show-exhaustion` lists any Allowances that are stopping the pool from getting instances. `yd allowance boost` raises one.
- **The instances may not be booting into the Agent.** An instance whose Agent hasn't registered within `nodeBootTimeout` (10 minutes by default) is terminated. Check that the image has the Agent installed, or that the User Data installs it (see [A First Run, with No Image of Your Own](worker-pools.md#a-first-run-with-no-image-of-your-own)), and look at an instance's console output in the cloud provider's console.
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
