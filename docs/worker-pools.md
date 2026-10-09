# Worker Pools

<!--ts-->
   * [Worker Pools vs. Compute Requirements](#worker-pools-vs-compute-requirements)
   * [Worker Pool Properties](#worker-pool-properties)
   * [Using Textual Names instead of IDs for Compute Requirement Templates and Image Families](#using-textual-names-instead-of-ids-for-compute-requirement-templates-and-image-families)
   * [Large-Scale Provisioning](#large-scale-provisioning)
   * [Automatic Properties](#automatic-properties)
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

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 09:37:24 BST 2026 -->

<!--te-->


A Provisioned **Worker Pool** is a set of cloud-provisioned compute instances running the YellowDog agent, which claim and execute Tasks from Work Requirements. Worker Pools are created using the **`yd-provision`** command and are automatically scaled and shut down based on demand and configured timeout settings.

**Jump to:** [Property Dictionary](#worker-pool-properties) · [TOML Example](#toml-properties-in-the-workerpool-section) · [JSON Spec](#worker-pool-specification-using-json-documents) · [Variable Substitutions](#variable-substitutions-in-worker-pool-properties) · [Dry-Running](#dry-running-worker-pool-provisioning) · [Node Actions](#node-actions)

The `workerPool` section of the TOML file defines the properties of the Worker Pool to be created, and is used by the `yd-provision` command. A subset of the properties is also used by the `yd-instantiate` command, for creating standalone Compute Requirements that are not associated with Worker Pools. Note that `computeRequirement` may be used as a synonym for `workerPool`, and the two may be used simultaneously in the same TOML file provided that their contained properties are not duplicated.

The only mandatory property is `templateId`. All other properties have defaults (or are not required).
The `templateId` property can use either the YellowDog ID ('YDID') for the Compute Requirement Template, or its name, optionally prefixed with its namespace (`namespace/name`). A name without a namespace is looked for in every namespace the Application can read, and is an error if templates of that name are found in more than one.

## Worker Pools vs. Compute Requirements

It is worth clarifying the distinction between the two related concepts:

- A **Worker Pool** (created by `yd-provision`) is a managed set of cloud instances running the YellowDog agent. The platform automatically scales the pool up and down to meet Task demand, and shuts it down when idle. Worker Pool nodes claim Tasks from Work Requirements and execute them.

- A **Compute Requirement** (created by `yd-instantiate`) is simply a set of cloud instances — there is no YellowDog Worker Pool associated with them. The instances are managed directly by the user. This is useful when you want to use YellowDog's provisioning capabilities but manage instances yourself.

Both use the same `workerPool` / `computeRequirement` TOML section for configuration, and both are terminated using `yd-terminate`.

## Worker Pool Properties

The following properties are available:

| Property                | Description                                                                                                                                       | Default                 |
|:------------------------|:--------------------------------------------------------------------------------------------------------------------------------------------------|:------------------------|
| `computeRequirementBatchSize` | The maximum number of instances per Compute Requirement batch (see [Large-Scale Provisioning](#large-scale-provisioning)). Values above 10,000 are clamped to 10,000; a value below 1 is an error. | `10000` |
| `computeRequirementData` | The name of a file containing a JSON specification of a Compute Requirement; used by `yd-instantiate` (see [yd-instantiate](commands.md#yd-instantiate)).  |                         |
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

Similarly, the `imagesId` property can be populated with the YDID of an Image Family, Image Group, Image, or a string representing the native name of a cloud provider image (e.g. an AWS AMI). It can also be populated with an Image Family name in the form `namespace/image_family_name`, or an Image Group name in the form `namespace/image_family_name/image_group_name` or `image_family_name/image_group_name`. Optionally, a `yd/` prefix can be supplied. The CLI will aim to map the provided name into an Image Family or Group YDID.

## Large-Scale Provisioning

The platform limits each Compute Requirement and Worker Pool to **10,000 instances/nodes**. When `targetInstanceCount` (for `yd-instantiate`) or `maxNodes` (for `yd-provision`) exceeds this limit, the CLI automatically splits the request across multiple Compute Requirements, distributing instances as evenly as possible.

The `computeRequirementBatchSize` property controls the maximum number of instances per batch and defaults to 10,000 (the platform maximum). Set it to a smaller value to submit in smaller batches. Values above 10,000 are clamped to 10,000 with a warning, and a value below 1 is an error.

## Automatic Properties

The name of the Worker Pool, if not supplied, is automatically generated using a concatenation of the `tag` property, a UTC timestamp and a process discriminator (see [Naming Rules](configuration.md#naming-rules)), e.g. `mytag_221024-1555241-4f`.

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

It's also possible to capture a Worker Pool definition as a JSON document. The JSON filename can be supplied either by supplying the command-line positional argument for `yd-provision`, or by populating the `workerPoolData` property in the TOML configuration file with the JSON filename. Command-line specification takes priority over TOML specification.

The JSON specification allows the creation of **Advanced Worker Pools**, with the ability to specify Node Actions and to differentiate Node Types.

When using a JSON document to specify the Worker Pool, the schema of the document is identical to that expected by the YellowDog REST API for Worker Pool Provisioning. The document is sent through the YellowDog SDK, as a TOML-defined Worker Pool is, so a property the installed SDK does not know is ignored with a warning (`Ignoring unexpected property`); upgrading the CLI's SDK makes a newly added property available. The same applies to a JSON Compute Requirement specification for `yd-instantiate`.

### Worker Pool JSON Examples

The example below is of a simple JSON specification of a Worker Pool with one initial node, Worker Pool shutdown, etc.

```json
{
  "requirementTemplateUsage": {
    "maintainInstanceCount": false,
    "requirementName": "pyex-primes_230113-1615283-4f",
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

Note that the `templateId` property can use either the YellowDog ID ('YDID') for the Compute Requirement Template, or its name. Similarly, the `imagesId` property can use either a YDID or the Image Family or Image Group name (e.g. `"yd-agent-docker"`).

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

Variable substitutions can be used within any property value in TOML configuration files or Worker Pool JSON files. See the description [above](variables.md#variable-substitutions) for more details on variable substitutions. This is a powerful feature that allows Worker Pools to be parameterised by supplying values on the command line, via environment variables, or via the TOML file.

An important distinction when using variable substitutions within Worker Pool (or Compute Requirement) JSON/Jsonnet documents is that each variable directive **must be prefixed and postfixed by a `__` (double underscore)** to disambiguate it from Mustache variable substitutions that must be passed directly to the API without client processing. For example, use: `__{{username}}__` to apply a substitution for the `username` default variable substitution.

In general, double underscores are **not** required in variable substitutions within the `workerPool` and/or `computeRequirement` sections of a TOML file. The exception to this is if the `userData` property is supplied, in which case double underscores **are** required. They are also required within any files referenced by the `userDataFile` or `userDataFiles` properties.

## Dry-Running Worker Pool Provisioning

To examine the JSON that will actually be sent to the YellowDog API after all processing, use the `--dry-run` command-line option when running `yd-provision`. This will print the JSON specification for the Worker Pool. Nothing will be submitted to the platform. Add `--hide-user-data` to show the User Data as a summary of its size, where a long script would otherwise swamp the rest of the specification.

The generated JSON is produced after all processing (incorporating `config.toml` properties, variable substitutions, etc.) has been concluded, so the dry-run is useful for inspecting the results of all the processing that's been performed.

To suppress all output except for the JSON itself, add the `--quiet` (`-q`) command-line option.

Use `--follow` (`-f`) to track the provisioning progress after submission — `yd-provision` will report on node events and not return until the Worker Pool reaches a stable state.

The JSON dry-run output could itself be used by `yd-provision`, if captured in a file, e.g.:

```shell
yd-provision --dry-run -q > my_worker_pool.json
yd-provision my_worker_pool.json
```

## Node Actions

Node Actions allow scripts and commands to be dispatched directly to running Worker Pool nodes. They can be used to start services (e.g. Slurm controllers), write configuration files, or create YellowDog Workers dynamically — without modifying the original Worker Pool specification. Node Actions are submitted using the **`yd-nodeaction`** command.

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
- **Interactive**: If neither flag is given, the Worker Pool's current nodes are displayed for interactive selection.

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
