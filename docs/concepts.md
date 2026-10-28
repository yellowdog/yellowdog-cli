# How a Task Finds a Worker

<!--ts-->
   * [The Pieces](#the-pieces)
   * [How the Matching Works](#how-the-matching-works)
      * [An Example](#an-example)
      * [Details](#details)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Wed Oct 28 08:25:43 GMT 2026 -->

<!--te-->

YellowDog runs your Tasks on Workers, and the YellowDog Scheduler decides which Workers. It matches each Task Group's **run specification** against the Worker Pools available, and a Task Group whose run specification no Worker matches waits. This page describes the pieces involved and how they are matched. [Why Isn't My Work Running?](troubleshooting.md) uses this to find what is stopping a Work Requirement.

## The Pieces

On the work side:

- A **Work Requirement** holds one or more **Task Groups**, each holding **Tasks**. `yd workrequirement submit` creates them (see [Work Requirements](work-requirements.md)).
- Each Task Group has a **run specification**: the Task Types its Tasks use, the Worker Tags it accepts, and any limits on where and on what its Tasks may run.

On the compute side:

- A **Worker Pool** is a set of **Nodes**. A Provisioned Worker Pool's Nodes are cloud instances, provisioned from a Compute Requirement Template; a Configured Worker Pool's are your own machines (see [Worker Pools](worker-pools.md)).
- A Node is an instance running the **YellowDog Agent**. The Agent registers the Node with the Platform, reporting its RAM, its vCPUs and the **Task Types** it can run.
- Each Node runs one or more **Workers**. A Worker runs one Task at a time, so a Node with four Workers runs four Tasks at once. `workersPerNode` or `workersPerVCPU` sets how many.
- Every Worker in a Worker Pool carries the pool's **Worker Tag**, if it has one.

## How the Matching Works

A Task Group **claims** Workers that match its run specification, and its Tasks are given to the Workers it has claimed. A Provisioned Worker Pool whose Workers match a Task Group that needs more of them is a candidate for scaling up, up to its `maxNodes`. A Worker Pool whose Workers no Task Group matches never grows, and shuts down when it has been idle for `idlePoolTimeout`.

These are the properties matched, and where each side's value comes from:

| Run specification property | Matched against | Which comes from |
|---|---|---|
| `taskTypes` | The Task Types a Node's Agent supports: it must support all of them | The Agent's `application.yaml` (see [Where Task Types Come From](work-requirements.md#where-task-types-come-from)) |
| `workerTags` | The Worker Pool's Worker Tag: it must be in the list | The pool's `workerTag` |
| `namespaces` | The Worker Pool's namespace: it must be in the list | The namespace the pool was provisioned in |
| `instanceTypes`, `providers`, `regions` | The instance types, cloud providers and regions of the pool's Compute Sources | The Compute Source Templates the pool's Compute Requirement Template uses |
| `ram`, `vcpus` | Each Node's reported RAM and vCPUs: they must be within the range | The instance type |

A property the Task Group leaves unset, or sets to an empty list, places no constraint: a Task Group with no `workerTags` accepts any Worker Tag. Most Task Groups set just `taskTypes` (which `yd workrequirement submit` fills in from the Tasks' `taskType`) and `workerTags`, and leave the rest unset.

### An Example

This configuration submits a Work Requirement and provisions a Worker Pool that match each other:

```toml
[workRequirement]
    taskType = "bash"                      # so the Task Group's taskTypes is ["bash"]
    arguments = ["-c", "echo Rendering frame {{task_number}}"]
    taskCount = 20
    workerTag = "render"                   # so its workerTags is ["render"]

[workerPool]
    templateId = "image-processing/ubuntu-small"
    imagesId = "ami-…"                     # a stock Ubuntu image in your region
    userDataFile = "yd-agent-installer.sh" # installs the Agent, which supports bash
    workerTag = "render"
    maxNodes = 4
```

The Task Group needs `bash`, which the Agent installer provides, and accepts the Worker Tag `render`, which the pool's Workers carry. It sets nothing else, so the pool's instance types, region and namespace are all acceptable. Change either `workerTag`, or the `taskType` to one the Agent does not support, and the Task Group finds no Workers.

`yd workrequirement compare` checks a Task Group against a Worker Pool property by property, and says which properties do not match (see [Comparing a Task Group with a Worker Pool](troubleshooting.md#comparing-a-task-group-with-a-worker-pool)).

### Details

**How many Workers a Task Group claims.** `maxWorkers` caps the Workers a Task Group claims, and `tasksPerWorker` sets how many unfinished Tasks share each claim. Its Tasks start as soon as it has claimed a Worker. `minWorkers` is the number of Workers it keeps once it has claimed them: it releases none that would take it below that number, even when it has fewer Tasks left.

**Dependencies.** A Task Group with `dependencies` waits until the Task Groups it names have completed, however many Workers match it.

**A Work Requirement on hold.** A Work Requirement submitted with `--hold`, or held with `yd workrequirement hold`, runs no Tasks until `yd workrequirement start` releases it.

**One Node's Task Types.** The Scheduler takes a Worker Pool's Task Types from one of its Nodes, so the Nodes of one pool should all support the same Task Types.

**Tasks queued on a Node.** By default, the Scheduler can allocate Tasks to a Node ahead of its Workers becoming free, where they wait their turn. `disablePreallocation` stops that, allocating each Task only as a Worker becomes idle.

**No fixed pairing.** A Worker Pool serves every Task Group that matches it, from any Work Requirement, and a Task Group can claim Workers from several Worker Pools at once.
