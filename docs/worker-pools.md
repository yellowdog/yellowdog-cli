# Worker Pools

<!--ts-->
   * [Examples](#examples)
      * [A Worker Pool from the Configuration File](#a-worker-pool-from-the-configuration-file)
      * [Installing Software as Each Node Boots](#installing-software-as-each-node-boots)
   * [Worker Pools vs. Compute Requirements](#worker-pools-vs-compute-requirements)
   * [Worker Pool Properties](#worker-pool-properties)
   * [Using Textual Names instead of IDs for Compute Requirement Templates and Image Families](#using-textual-names-instead-of-ids-for-compute-requirement-templates-and-image-families)
      * [Details](#details)
   * [Large-Scale Provisioning](#large-scale-provisioning)
      * [Details](#details-1)
   * [Automatic Properties](#automatic-properties)
   * [All Properties in the workerPool Section](#all-properties-in-the-workerpool-section)
   * [Worker Pool Specification Using JSON Documents](#worker-pool-specification-using-json-documents)
      * [Worker Pool JSON Examples](#worker-pool-json-examples)
      * [TOML Properties Inherited by Worker Pool JSON Specifications](#toml-properties-inherited-by-worker-pool-json-specifications)
         * [Details](#details-2)
   * [Variable Substitutions in Worker Pool Properties](#variable-substitutions-in-worker-pool-properties)
      * [Details](#details-3)
   * [Following a Worker Pool](#following-a-worker-pool)
   * [Dry-Running Worker Pool Provisioning](#dry-running-worker-pool-provisioning)
   * [Node Actions](#node-actions)
      * [Action Types](#action-types)
      * [Spec File Structure](#spec-file-structure)
         * [Actions](#actions)
         * [Action Groups](#action-groups)
      * [Action Fields Reference](#action-fields-reference)
         * [Common Fields (all action types)](#common-fields-all-action-types)
      * [Node Selection](#node-selection)
         * [Details](#details-4)
      * [Worker Pool Selection](#worker-pool-selection)
      * [Checking Node Action Queue Status](#checking-node-action-queue-status)
         * [Details](#details-5)
      * [Following Progress](#following-progress)
         * [Details](#details-6)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:19:02 GMT 2026 -->

<!--te-->


A Provisioned **Worker Pool** is a set of cloud-provisioned compute instances running the YellowDog agent, which claim and execute Tasks from Work Requirements. Worker Pools are created using the **`yd workerpool provision`** command and are automatically scaled and shut down based on demand and configured timeout settings.

**Jump to:** [Property Dictionary](#worker-pool-properties) · [Examples](#examples) · [All TOML Properties](#all-properties-in-the-workerpool-section) · [JSON Spec](#worker-pool-specification-using-json-documents) · [Variable Substitutions](#variable-substitutions-in-worker-pool-properties) · [Dry-Running](#dry-running-worker-pool-provisioning) · [Node Actions](#node-actions)

The `workerPool` section of the TOML file defines the properties of the Worker Pool to be created, and is used by the `yd workerpool provision` command. The `yd computerequirement instantiate` command uses a subset of the same properties to create standalone Compute Requirements, which have no Worker Pool.

`computeRequirement` is a synonym for `workerPool`. Both sections may be present in the same TOML file, as long as no property is set in both.

The only mandatory property is `templateId`, the Compute Requirement Template to provision from. It takes the template's YellowDog ID (YDID) or its name, optionally prefixed with its namespace (`namespace/name`); see [Using Textual Names](#using-textual-names-instead-of-ids-for-compute-requirement-templates-and-image-families). All other properties have defaults, or are optional.

## Examples

Each example runs in a directory whose `config.toml` holds your Application key and secret, namespace and tag in its `[common]` section, as `yd init` writes them. `templateId` names a Compute Requirement Template you have already created, whose image runs the YellowDog Agent; the [Cloud Wizard](../README_CLOUDWIZARD.md) can create one for you.

### A Worker Pool from the Configuration File

This `[workerPool]` section provisions a pool for Tasks with the Worker Tag `render`, such as those in the [Work Requirement examples](work-requirements.md#examples):

```toml
[workerPool]
    templateId = "image-processing/ubuntu-small"
    maxNodes = 4
    workerTag = "render"
    workersPerVCPU = 1
    idleNodeTimeout = 10
```

```bash
yd workerpool provision
```

The pool starts with one node and can grow to four. Each node runs one Worker per vCPU, so it runs that many Tasks at once. A node with no work for 10 minutes is shut down, and the pool shuts itself down after 30 idle minutes (`idlePoolTimeout`). Add `--dry-run` to print the Worker Pool without provisioning it, or `--follow` to follow it until it shuts down.

### Installing Software as Each Node Boots

User Data is a script each instance runs as it boots. To install `ffmpeg` on every node, put the script in a file:

```bash
#!/bin/bash
apt-get update && apt-get install -y ffmpeg
```

and name the file with `userDataFile`:

```toml
[workerPool]
    templateId = "image-processing/ubuntu-small"
    maxNodes = 4
    workerTag = "render"
    userDataFile = "install-ffmpeg.sh"
```

The file is found next to `config.toml`, or in the `--content-path` directory if one is given. Use `--dry-run --hide-user-data` to check the rest of the specification without the script in the output.

## Worker Pools vs. Compute Requirements

It is worth clarifying the distinction between the two related concepts:

- A **Worker Pool** (created by `yd workerpool provision`) is a managed set of cloud instances running the YellowDog agent. The platform automatically scales the pool up and down to meet Task demand, and shuts it down when idle. Worker Pool nodes claim Tasks from Work Requirements and execute them.

- A **Compute Requirement** (created by `yd computerequirement instantiate`) is simply a set of cloud instances — there is no YellowDog Worker Pool associated with them. The instances are managed directly by the user. This is useful when you want to use YellowDog's provisioning capabilities but manage instances yourself.

Both use the same `workerPool` / `computeRequirement` TOML section for configuration. A Worker Pool is shut down using `yd workerpool shutdown` (with `--terminate` to terminate its instances at once), and a Compute Requirement is terminated using `yd computerequirement terminate`.

## Worker Pool Properties

The following properties are available:

| Property                | Description                                                                                                                                       | Default                 |
|:------------------------|:--------------------------------------------------------------------------------------------------------------------------------------------------|:------------------------|
| `autoShutdownTimeout`   | Only used when instantiating Compute Requirements; the time in minutes after which the Compute Requirement will be terminated. Set this to `0` to disable it. `yd computerequirement autoshutdown` changes it later (see [yd computerequirement autoshutdown](commands.md#yd-computerequirement-autoshutdown)). A Worker Pool ignores it, with a warning: it shuts down when idle instead. |                         |
| `computeRequirementBatchSize` | The maximum number of instances per Compute Requirement batch (see [Large-Scale Provisioning](#large-scale-provisioning)). Values above 10,000 are clamped to 10,000; a value below 1 is an error. | `10000` |
| `computeRequirementData` | The name of a file containing a JSON specification of a Compute Requirement; used by `yd computerequirement instantiate` (see [yd computerequirement instantiate](commands.md#yd-computerequirement-instantiate)).  |                         |
| `idleNodeTimeout`       | The timeout in minutes after which an idle node will be shut down. Set this to `0` to disable the timeout.                                        | `5.0`                   |
| `idlePoolTimeout`       | The timeout in minutes after which an idle Worker Pool will be shut down. Set this to `0` to disable the timeout.                                 | `30.0`                  |
| `imagesId`              | The Image ID, Image Family ID, Image Family name, or Image Group name to use when booting instances.                                              |                         |
| `instanceTags`          | The dictionary of instance tags to apply to the instances. Tag names must be lower case.                                                          |                         |
| `maintainInstanceCount` | Only used when instantiating Compute Requirements; attempt to maintain the requested number of instances.                                         | `false`                 |
| `maxNodes`              | The maximum number of nodes to which the Worker Pool can be scaled up.                                                                            | `targetInstanceCount`, or `1` if that is `0` |
| `metricsEnabled`        | Whether to enable performance metrics for nodes in the Worker Pool                                                                                | `false`                 |
| `minNodes`              | The minimum number of nodes to which the Worker Pool can be scaled down.                                                                          | `0`                     |
| `name`                  | The name of the Worker Pool.                                                                                                                      | Automatically Generated |
| `nodeBootTimeout`       | The time in minutes allowed for a node to boot and register with the platform, otherwise it will be terminated.                                   | `10.0`                  |
| `requirementTag`        | The tag to apply to the Compute Requirement.                                                                                                      | `tag` set in `common`   |
| `targetInstanceCount`   | The initial number of nodes to create in the Worker Pool.                                                                                         | `1`                     |
| `templateId`            | The YellowDog Compute Requirement Template ID or name to use for provisioning. (**Required**)                                                     | No default provided     |
| `userData`              | User Data to be supplied to instances on boot.                                                                                                    |                         |
| `userDataFile`          | As above, but read the User Data from the filename supplied in this property, found from `--content-path`, else the configuration file's directory. |                         |
| `userDataFiles`         | As above, but create the User Data by concatenating the contents of the list of filenames supplied in this property, a newline after each.       |                         |
| `workerPoolData`        | The name of a file containing a JSON specification of a Worker Pool (see [Worker Pool JSON](#worker-pool-specification-using-json-documents)), relative to the configuration file; not to be set with `computeRequirementData`. |                         |
| `workerTag`             | The Worker Tag to publish for each of the Workers on the node(s).                                                                                 |                         |
| `workersPerNode`        | The number of Workers to establish on each node in the Worker Pool. Used when neither `workersPerVCPU` nor `workersCustomCommand` is set.          | `1`                     |
| `workersPerVCPU`        | The number of Workers to establish per vCPU on each node in the Worker Pool, which may be a fraction (`0.5` is one Worker for every two vCPUs). Takes precedence over `workersPerNode`. |                         |
| `workersCustomCommand`  | A command run on the node to determine the number of Workers to establish. Takes precedence over `workersPerNode` and `workersPerVCPU`.         |                         |

## Using Textual Names instead of IDs for Compute Requirement Templates and Image Families

`templateId` and `imagesId` take names as well as YellowDog IDs (YDIDs), so a configuration can name what it uses:

```toml
[workerPool]
    templateId = "image-processing/ubuntu-small"
    imagesId = "image-processing/render-images"
```

`templateId` takes a Compute Requirement Template's YDID, or its name, optionally prefixed with its namespace (`namespace/template_name`).

`imagesId` takes any of these:

- The YDID of an Image Family, Image Group or Image
- The native name of a cloud provider image, such as an AWS AMI ID
- An Image Family name, on its own or as `namespace/image_family_name`
- An Image Group name, as `namespace/image_family_name/image_group_name` or `image_family_name/image_group_name`

The CLI maps a name to the Image Family or Image Group's YDID.

### Details

**Template names without a namespace.** A template name without a namespace is looked for in every namespace the Application can read. If templates of that name are found in more than one namespace, it is an error.

**The `yd/` prefix.** An `imagesId` name may optionally be given a `yd/` prefix.

## Large-Scale Provisioning

The Platform limits each Compute Requirement and Worker Pool to **10,000 instances/nodes**. A larger Worker Pool or Compute Requirement in the configuration file is split across several, with the instances distributed as evenly as possible. For example, with this configuration:

```toml
[workerPool]
    name = "render-pool"
    templateId = "image-processing/ubuntu-small"
    maxNodes = 25000
    workerTag = "render"
```

`yd workerpool provision` provisions three Worker Pools, `render-pool_1` with a `maxNodes` of 8,334 and `render-pool_2` and `render-pool_3` with 8,333 each.

The split is made when `maxNodes` (for `yd workerpool provision`) or `targetInstanceCount` (for `yd computerequirement instantiate`) exceeds the batch size. Set `computeRequirementBatchSize` to submit in smaller batches; it defaults to 10,000, the Platform maximum.

### Details

**Names and `minNodes`.** Each batch's name is the name with its batch number added. `minNodes` is divided between the batches as the instances are.

**JSON specifications.** Only a Worker Pool or Compute Requirement defined in the configuration file is split. A JSON specification is provisioned as one, with a warning when its `maxNodes` exceeds the batch size.

**Batch size limits.** A `computeRequirementBatchSize` above 10,000 is clamped to 10,000 with a warning, and a value below 1 is an error.

## Automatic Properties

The name of the Worker Pool, if not supplied, is automatically generated using a concatenation of the `tag` property, a UTC timestamp and a process discriminator (see [Naming Rules](configuration.md#naming-rules)), e.g. `mytag_221024-1555241-4f`.

## All Properties in the `workerPool` Section

Every property the `workerPool` section of a TOML configuration file can set, for reference: it is not meant to be used as it stands. The [Worker Pool Properties](#worker-pool-properties) table describes each property, and the [Examples](#examples) show typical use.

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

A Worker Pool can also be defined as a JSON document. Name the file on the command line:

```bash
yd workerpool provision render-pool.json
```

or with the `workerPoolData` property in the TOML configuration file. A file named on the command line takes priority over `workerPoolData`.

The JSON specification allows the creation of **Advanced Worker Pools**, with the ability to specify Node Actions and to differentiate Node Types. Its schema is the one the YellowDog REST API expects for Worker Pool Provisioning.

The document is sent through the YellowDog SDK, as a TOML-defined Worker Pool is. A property the installed SDK does not know is ignored with a warning (`Ignoring unexpected property`); upgrading the CLI's SDK makes a newly added property available. The same applies to a JSON Compute Requirement specification for `yd computerequirement instantiate`.

### Worker Pool JSON Examples

This JSON specification provisions a Worker Pool that starts with one node and can grow to five, running one Worker per vCPU, with nodes shut down after 10 idle minutes and the pool after an idle hour. Its name is generated, as it sets no `requirementName`.

```json
{
  "requirementTemplateUsage": {
    "maintainInstanceCount": false,
    "requirementNamespace": "image-processing",
    "requirementTag": "render",
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
    "workerTag": "render"
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

A JSON Worker Pool specification takes the properties it leaves out from the `[workerPool]` section of `config.toml`. So a specification can hold only what is particular to the pool, and the configuration file supplies the template, the namespace and the rest.

**Properties Inherited within the `requirementTemplateUsage` property**

- `imagesId`
- `instanceTags`
- `requirementName`: from the configuration's `name`
- `requirementNamespace`: from the `namespace` in the `[common]` section
- `requirementTag`: from the `requirementTag` in the `[workerPool]` section, else the `tag` in the `[common]` section
- `targetInstanceCount`, if the configuration sets it (or `--target` gives it)
- `templateId`
- `userData`: from the configuration's `userData`, or read from its `userDataFile` or `userDataFiles`

Like the configuration's own, `templateId` and `imagesId` may be names (e.g. `"yd-agent-docker"`) as well as YDIDs (see [Using Textual Names](#using-textual-names-instead-of-ids-for-compute-requirement-templates-and-image-families)).

**Properties Inherited within the `provisionedProperties` Property**

- `idleNodeTimeout` (set to `0` to disable)
- `idlePoolTimeout` (set to `0` to disable)
- `maxNodes`, if the configuration sets it
- `metricsEnabled`
- `minNodes`, if the configuration sets it
- `nodeBootTimeout`
- `workerTag`
- `workersPerNode`, `workersPerVCPU`, or `workersCustomCommand`

#### Details

**Defaults.** The timeouts, the Worker count and `metricsEnabled` are inserted with their defaults when the configuration does not set them. `minNodes`, `maxNodes` and `targetInstanceCount` are inserted only when it does. The default Worker count is `workersPerNode = 1`; set `workersPerNode = 0` in the configuration to insert a Worker count of `0` instead.

**`--property` overrides.** A property given with `--property workerPool.<key>=<value>` replaces the specification's own value, rather than only filling it in when absent (see [Which Value Wins](configuration.md#which-value-wins)).

**The name.** The name is generated automatically if neither the configuration nor the specification supplies one.

**User Data.** `userDataFile` and `userDataFiles` are configuration properties only, not specification ones. The configuration's User Data is used only if the specification has no `userData` of its own.

## Variable Substitutions in Worker Pool Properties

Variable substitutions can be used within any property value in TOML configuration files or Worker Pool JSON files, so a Worker Pool can be parameterised by values supplied on the command line, in environment variables or in the TOML file. See [Variable Substitutions](variables.md) for more details.

```toml
[workerPool]
    name = "render-{{region}}"
    templateId = "image-processing/ubuntu-small"
    maxNodes = "{{num:max_nodes:=4}}"
    userDataFile = "install-ffmpeg.sh"
```

```bash
yd workerpool provision -v region=eu-west
```

This provisions the Worker Pool `render-eu-west`, with a `maxNodes` of 4 unless `-v max_nodes=...` gives another.

In User Data and in Node Actions, write a substitution with a double underscore before and after it, e.g. `__{{region}}__`. A plain `{{...}}` there is left for the Platform's Mustache processing. For example, the script in `install-ffmpeg.sh` could record the region with `echo __{{region}}__ > /etc/render-region`.

### Details

**Where the `__` form is needed.** User Data takes the `__{{...}}__` form wherever it is given. So do Node Actions (`nodeEvents`), in a Worker Pool specification or a Configured Worker Pool resource.

**Everywhere else.** Every other property of a Worker Pool (or Compute Requirement) JSON or Jsonnet specification takes either `__{{username}}__` or the plain `{{username}}`. The configuration file's `workerPool` and `computeRequirement` sections take the plain form.

The full rule, place by place, is in [Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data](variables.md#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data).

## Following a Worker Pool

Use `--follow` (`-f`) to track the Worker Pool after submission:

```bash
yd workerpool provision --follow
```

`yd workerpool provision` then reports the Worker Pool's node events and does not return until the Worker Pool has shut down, or Ctrl-C is pressed. Add `--auto-follow-compute-requirements` (`-a`) to follow its Compute Requirements too.

## Dry-Running Worker Pool Provisioning

To see the JSON that would be sent to the YellowDog API, without provisioning anything, add `--dry-run` (`-D`) to `yd workerpool provision`:

```bash
yd workerpool provision --dry-run
```

The JSON is produced after all processing has been concluded: the `config.toml` properties incorporated, the variables substituted, and so on. So a dry run shows the results of all of it.

Add `--quiet` (`-q`) to print the JSON alone, and `--hide-user-data` to show the User Data as a summary of its size, where a long script would otherwise swamp the rest of the specification.

The output can itself be provisioned by `yd workerpool provision`, if captured in a file:

```shell
yd workerpool provision --dry-run -q > render-pool.json
yd workerpool provision render-pool.json
```

## Node Actions

Node Actions dispatch scripts and commands directly to running Worker Pool nodes. Use them to start services (e.g. Slurm controllers), write configuration files, or create YellowDog Workers, without changing the Worker Pool's specification. Node Actions are submitted using the **`yd node action`** command.

For example, this `start-render.json` writes a settings file on each node, starts a service, and then creates one Worker per vCPU:

```json
{
  "actions": [
    {
      "type": "writeFile",
      "path": "/etc/render/settings.json",
      "content": "{\"licenseServer\": \"__{{license_server}}__\"}"
    },
    {
      "type": "runCommand",
      "path": "/opt/render/bin/start-render-service.sh"
    },
    {
      "type": "createWorkers",
      "nodeWorkers": {"targetType": "PER_VCPU", "targetCount": 1}
    }
  ]
}
```

To send it to every node in the Worker Pool `render-pool` and follow the actions until they finish:

```bash
yd node action --actions start-render.json --worker-pool render-pool --all-nodes -v license_server=licence.example.com --follow
```

### Action Types

There are three action types:

| Type            | Description                          |
|:----------------|:-------------------------------------|
| `runCommand`    | Execute a command on the node        |
| `writeFile`     | Write a file to the node             |
| `createWorkers` | Create YellowDog Workers on the node |

These are the `yd node action` file's own names, from which the CLI builds the Platform's actions. A Worker Pool specification's `nodeEvents` are sent to the Platform as written, so they use the Platform's form instead, `"action": "RUN_COMMAND"`, `"WRITE_FILE"` and `"CREATE_WORKERS"`, as in the [Advanced Worker Pool example](#worker-pool-json-examples).

### Spec File Structure

Node actions are defined in a JSON (or Jsonnet) spec file supplied via the `--actions` option. The spec is a JSON object containing either an `actions` key, a flat list of actions, or an `actionGroups` key, a list of action groups, each of which is a flat list of actions.

Actions in an actions list are downloaded by a node in one operation and executed sequentially.

Variable substitutions in spec files use the `__{{variable}}__` form throughout, as a Worker Pool specification's own Node Actions do. The content may include Mustache templates, which the Platform processes, and a plain `{{...}}` is left for it; see [which form to use](variables.md#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data).

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
      "path": "/etc/render/settings.json",
      "content": "{\"licenseServer\": \"__{{license_server}}__\"}"
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

Grouped actions are submitted as a unit to the pool, but nodes execute them one group at a time:

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

Only one of `content`, `contentFile` and `contentFiles` may be given. All three take variable substitutions in the `__{{variable}}__` form.

A relative `contentFile` path is found from `--content-path`, else the specification file's directory, else the configuration file's.

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

Target nodes are chosen in one of three ways:

- **`--node <id>`**: submit to a specific node, given by its YDID. Repeat it for several nodes.
- **`--all-nodes`**: broadcast to all current nodes in the pool.
- **Interactive**: with neither option, the Worker Pool's current nodes are listed for you to choose from.

The same applies to grouped actions: `--all-nodes` applies the groups to all nodes, `--node` to the nodes given, and with neither you choose the nodes.

#### Details

**Several nodes.** The nodes given with `--node` must all be in one Worker Pool. That Worker Pool is found from them, without prompting (see [Worker Pool Selection](#worker-pool-selection)).

**Finished nodes.** A node given with `--node` that has finished is skipped with a warning.

### Worker Pool Selection

The `--worker-pool` option accepts either a Worker Pool name or a Worker Pool YDID. If it is omitted, you choose from the unfinished Worker Pools in the configured `namespace` whose names include the `tag`.

When `--node` is given and `--worker-pool` is omitted, the Worker Pool is found from the nodes, and you are not asked to choose one.

### Checking Node Action Queue Status

The `--status` option shows the action queue of the selected nodes as one table. For each node, the table shows its Node ID, the queue's status, the number of waiting actions, the action executing now, and any failed action:

```shell
yd node action --status --worker-pool render-pool
yd node action --status --node ydid:node:D9C548:7c2b1e94-3f5a-4d8e-b6a1-0e9f2c4d5a73
```

Add `--details` for the full JSON of each queue:

```shell
yd node action --status --node ydid:node:D9C548:7c2b1e94-3f5a-4d8e-b6a1-0e9f2c4d5a73 --details
```

#### Details

**Without a Worker Pool.** When `--node` is given, `--status` goes directly to the node without asking for a Worker Pool.

**Options it excludes.** `--status` submits nothing, so it cannot be combined with `--actions`, `--validate` or `--jsonnet-dry-run`. `--details` needs `--status`.

### Following Progress

Use `--follow` to watch the node action queues after submission. A status table is printed every few seconds until every queue is `EMPTY` or `FAILED`:

```shell
yd node action --actions start-render.json --node ydid:node:D9C548:7c2b1e94-3f5a-4d8e-b6a1-0e9f2c4d5a73 --follow
```

`--follow` can also be combined with `--status`, to watch a queue already running without submitting new actions:

```shell
yd node action --status --node ydid:node:D9C548:7c2b1e94-3f5a-4d8e-b6a1-0e9f2c4d5a73 --follow
```

#### Details

**With `--all-nodes`.** `--follow` works with `--all-nodes` too. The current node list is fetched from the Worker Pool at follow time.

**Polling.** The queues are polled every 5 seconds, not streamed.

**Time limit.** `--timeout <seconds>` stops following after that many seconds. If any queue has not finished by then, the command fails, exiting 1.
