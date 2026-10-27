# Creating, Updating and Removing YellowDog Resources

<!--ts-->
   * [Overview of Operation](#overview-of-operation)
         * [Details](#details)
      * [Resource Creation](#resource-creation)
      * [Resource Update](#resource-update)
         * [Details](#details-1)
      * [Resource Removal](#resource-removal)
         * [Details](#details-2)
      * [Resource Matching](#resource-matching)
   * [Resource Specification Definitions](#resource-specification-definitions)
   * [Generating Resource Specifications using yd list](#generating-resource-specifications-using-yd-list)
      * [Usage Scenario: Moving or Copying Resources to a New Namespace](#usage-scenario-moving-or-copying-resources-to-a-new-namespace)
   * [Specifying a Resource on the Command Line](#specifying-a-resource-on-the-command-line)
         * [Details](#details-3)
   * [Preprocessing Resource Specifications](#preprocessing-resource-specifications)
   * [Keyrings](#keyrings)
   * [Credentials](#credentials)
   * [Compute Source Templates](#compute-source-templates)
         * [Details](#details-4)
   * [Compute Requirement Templates](#compute-requirement-templates)
         * [Details](#details-5)
   * [Image Families](#image-families)
         * [Details](#details-6)
   * [Configured Worker Pools](#configured-worker-pools)
         * [Details](#details-7)
   * [Allowances](#allowances)
         * [Details](#details-8)
   * [Attribute Definitions](#attribute-definitions)
      * [String Attribute Definitions](#string-attribute-definitions)
      * [Numeric Attribute Definitions](#numeric-attribute-definitions)
   * [Namespace Policies](#namespace-policies)
   * [Groups](#groups)
         * [Details](#details-9)
   * [Applications](#applications)
         * [Details](#details-10)
      * [Granting Keyring Access](#granting-keyring-access)
      * [Creating and Regenerating Application Keys](#creating-and-regenerating-application-keys)
   * [Users](#users)
         * [Details](#details-11)
   * [Namespaces](#namespaces)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:12:22 GMT 2026 -->

<!--te-->


The commands **yd resource create** and **yd resource remove** create, update and remove YellowDog resources from specification files. For example, to create a Keyring, write its specification to `keyring.json`:

```json
{"resource": "Keyring", "name": "render-keys", "description": "Keys for the render pipeline"}
```

and create it:

```shell
yd resource create keyring.json
```

These resource types are supported:

- Keyrings
- Credentials
- Compute Source Templates
- Compute Requirement Templates
- Image Families, Image Groups, and Images
- Namespaces
- Configured Worker Pools
- Allowances
- String Attribute Definitions
- Numeric Attribute Definitions
- Namespace Policies
- Groups
- Applications
- Users (update only)

## Overview of Operation

**yd resource create** and **yd resource remove** each take one or more resource specification files. A file can hold a single resource specification or a list of them, and different resource types can be mixed in the same list.

```shell
yd resource create keyrings.json templates.json
```

Resource specification files can use all forms of **variable substitution**, just as Work Requirement specifications can.

#### Details

**File formats.** A specification file is JSON or Jsonnet. A TOML file is also accepted, holding one resource.

**Checking a file offline.** `yd resource create --validate` checks the files against their schema and stops. `yd schema resources` prints that schema. Neither contacts the Platform.

**Processing order.** The complete list of resource specifications is re-sequenced so that dependent resources are dealt with in a suitable order. For example, all Compute Source Templates are processed before any Compute Requirement Templates on creation, and the reverse order is used on removal.

**`--no-resequence`.** This option disables the re-sequencing, on `yd resource create` and `yd resource remove` alike, and processes the resources strictly in the order in which they appear. For `yd resource remove`, that is the files' resources and the YellowDog IDs together, in the order given. It is occasionally useful when the order supplied is deliberate and the automatic sequencing would disturb it. A dependent resource listed before a resource it depends on then fails to be created.

### Resource Creation

To create resources, give `yd resource create` their specification files:

```shell
yd resource create keyrings.json templates.json
```

### Resource Update

To update resources, edit their specifications and run `yd resource create` again with the same files. Each update asks for approval first; `--yes` skips the prompt, as in other commands.

```shell
yd resource create --yes templates.json
```

#### Details

**Create or update.** A resource not already present in the Platform is created, and one that is present is updated. The command does not check for differences, so an unchanged resource specification still causes an update.

**Exceptions.** Four resource types behave differently:

- A **Credential** is put into its Keyring, replacing one of the same name, without a prompt.
- A **Namespace** that already exists is reported with a warning and skipped.
- An **Allowance** is created again, as a second Allowance. With `--match-allowances-by-description`/`-M`, it replaces those with the same description instead (see [Allowances](#allowances)).
- A **Configured Worker Pool** is always added as a new pool.

### Resource Removal

To remove resources, give `yd resource remove` the same specification files. It asks for approval before removing anything; `--yes` skips the prompt, as in other commands.

```shell
yd resource remove keyrings.json templates.json
```

Resources can also be removed by their YellowDog IDs, given in place of, or alongside, specification files:

```shell
yd resource remove ydid:crt:D9C548:2a09093d-c74c-4bde-95d1-c576c6f03b13 ydid:imgfam:D9C548:4bc3cc57-1387-49a6-85d4-132bcf3a65fd
```

#### Details

**Types removable by ID.** Compute Source and Compute Requirement Templates, Machine Image Families, Image Groups and Images, Keyrings, Allowances, Groups and Applications can be removed by ID, and Worker Pools shut down. An ID of any other type is refused.

**Checks before removal.** Every ID is checked before anything is removed. An ID given twice is removed once. The `--ids` option is optional, since an ID is recognised as one: it says every argument is an ID, and refuses anything else.

**Files and IDs together.** Files and IDs given together are removed in one run, ordered so that a resource is removed before those it refers to.

**A resource that does not exist.** Each resource is fetched before it is removed. One given by ID that does not exist is reported as not found, without a prompt, with exit code 6. One named in a specification file, or by name with `--type`, that does not exist is warned of and recorded as `skipped` instead, with exit code 0. A Worker Pool that has already been shut down is skipped.

### Resource Matching

Resources match on **resource names** and (where applicable) **resource namespaces** rather than on YellowDog IDs. This allows the `yd resource create` and `yd resource remove` commands to be stateless: there is no need to keep a local record of the YellowDog IDs of the resources created.

However, this means that **caution is required** when updating or removing resources, since matching uses **only** the **namespace/name** of the resource, never its `ydid`. A resource with a given name could have been removed and replaced in the Platform by some other means, and the resource specification would still match it.

## Resource Specification Definitions

The JSON specification for each type of resource is given by the YellowDog Platform REST API documentation at https://docs.yellowdog.ai/api, or as a schema, built from the installed SDK, by `yd schema resources`.

For example, the models for creating a Compute Source Template are in the REST API documentation for the Compute API: https://docs.yellowdog.ai/api?spec=Compute%20API.

Every specification used with `yd resource create` and `yd resource remove` also carries a `resource` property, which identifies the type of resource. It takes one of these values:

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
- `"InternalUser"`, `"ExternalUser"` (update only)
- `"Namespace"`

## Generating Resource Specifications using `yd list`

To capture resources already in the Platform as specifications, use `yd list` with `--details`, `--substitute-ids`/`-U` and `--strip-ids`, and select the resources wanted:

```shell
yd list compute-source-templates --details --substitute-ids --strip-ids
yd list compute-requirement-templates --details --substitute-ids --strip-ids
yd list image-families --details --substitute-ids --strip-ids
```

This produces a list of resource specifications that can be used directly with `yd resource create` and `yd resource remove`.

The `--output-file` option also writes the detailed list to a file, as well as displaying it:

```shell
yd list compute-source-templates --details --output-file render-templates.json
```

Alternatively, `yd show` gives the details of each resource whose `ydid` it is given. This writes a JSON file that can be used with `yd resource create` as it is, or edited:

```shell
yd show -q ydid:cst:000000:cde265f8-0b17-4e0e-be1c-505174a620e4 --substitute-ids --strip-ids --output-file aws-eu-west-2-ondemand.json
```

Both `yd list` and `yd show` take these two options:

- `--substitute-ids`/`-U` replaces IDs with names, to make the output easier to reuse. In a Compute Requirement Template, it replaces Compute Source Template IDs and Image Family and Group IDs. In a Compute Source Template, it replaces Image Family and Group IDs.
- `--strip-ids` removes the YellowDog IDs ('ydids') from the JSON output, as well as any other properties not needed to use the output with `yd resource create`.

### Usage Scenario: Moving or Copying Resources to a New Namespace

In this scenario, a set of resources is moved from the namespace `render-dev` to `render-prod`: all its Compute Source Templates, Compute Requirement Templates and Image Families.

**Step 1: Capture the target resources in JSON files**

```shell
yd list compute-source-templates -q --namespace render-dev --substitute-ids --strip-ids --auto-select-all --output-file csts.json
yd list compute-requirement-templates -q --namespace render-dev --substitute-ids --strip-ids --auto-select-all --output-file crts.json
yd list image-families -q --namespace render-dev --substitute-ids --strip-ids --auto-select-all --output-file ifs.json
```

**Step 2: Remove all target resources** if moving resources

This removes every resource in the files **without asking for confirmation**. To **copy** the resources to the new namespace rather than move them, skip this step.

```shell
yd resource remove -y csts.json crts.json ifs.json
```

**Step 3: Change the namespace in all the resources**

Replace the namespace wherever the files name it. That is every `namespace` property (`"render-dev"`), and the references `--substitute-ids` wrote, which name a resource by its namespace: a Compute Requirement Template's sources (`"render-dev/aws-eu-west-2-ondemand"`) and an Image Family (`"yd/render-dev/ubuntu-render-agent"`). A reference left unchanged would point at the resource removed in step 2. With `sed`, for example:

```shell
sed -i.bak -e 's#"render-dev"#"render-prod"#g' -e 's#"render-dev/#"render-prod/#g' -e 's#"yd/render-dev/#"yd/render-prod/#g' csts.json crts.json ifs.json
```

**Step 4: Recreate all resources in the new namespace**

```shell
yd resource create -y csts.json crts.json ifs.json
```

Once the resources have been created, the JSON files can be deleted, or kept for your records.

## Specifying a Resource on the Command Line

A resource with only a few properties can be given on the command line instead of in a file. `--type` names its resource type (any of those above, in any case), and each `--set property=value` gives one of its properties. `yd resource remove` takes them too, removing the resource they name.

```shell
yd resource create --type Namespace --set name=render-dev
yd resource create --type Keyring --set name=render-keys --set description="Keys for the render pipeline"
yd resource create --type StringAttributeDefinition --set name=user.gpu --set title="GPU type" \
    --set 'options=["a100", "h100"]'
yd resource remove --type Keyring --set name=render-keys
```

`yd resource remove` also takes the names or IDs of resources of the `--type` given as its arguments, in place of specification files:

```shell
yd resource remove --type Keyring render-keys test-keys
yd resource remove --type ComputeRequirementTemplate render-prod/gpu-render ydid:crt:000000:230e9a42-97db-4d69-aa91-29ff309951b4
yd resource remove --type Credential render-keys/aws-creds
```

`yd resource show` finds a resource by name in the same way:

```shell
yd resource show --type ComputeSourceTemplate render-prod/aws-eu-west-2-ondemand
```

A specification can also be read from standard input, as JSON, by giving `-` in place of a file name, for a script that writes one:

```shell
generate-keyrings | yd resource create -
```

#### Details

**How `--set` values are read.** A value is read as JSON where it can be, so `10` is a number, `true` a boolean, `null` null, and `[...]` and `{...}` a list and an object. Anything else is read as text. A property that takes text keeps the text as typed (`--set name=123` is the name `123`), as `--property` reads a value. Variables are substituted in the values, as in a file's (`--set name='{{tag}}-keys'`).

**Rules for `--type` and `--set`.** A property is given once. The type is given with `--type` alone, not as `--set resource=...`. A resource given this way is checked against the schema, processed, reported and recorded exactly as one in a file is, and can be given with files too.

**Naming a resource to remove.** A namespaced resource (a Compute Source or Requirement Template, an Image Family, a Configured Worker Pool) is named `namespace/name`, or by its name alone in the configured namespace. With no namespace configured, as with `-n ''`, a name alone is refused rather than looked for in every namespace. A Credential is named `keyring/credential`, and a Namespace Policy by its namespace.

**Resources removed by ID or by name only.** An Allowance has no name, so is removed by its ID, or with `--set description=...` and `--match-allowances-by-description`. A Namespace, Namespace Policy, Attribute Definition or Credential has no ID that removes it, so is removed by name. Users are not removed by the CLI.

**Several names and IDs.** Names and IDs can be mixed, and each is removed once. An argument of the wrong kind, such as another type's ID, is refused before anything is removed. One that fails does not stop the rest.

**Showing by name.** `yd resource show` finds every type with a name this way, for example `--type Keyring render-keys`, `--type NamespacePolicy render-dev` or `--type Credential render-keys/aws-creds`. An Allowance is shown by its ID.

## Preprocessing Resource Specifications

To see the processed JSON without creating or updating anything, use `--dry-run`/`-D` with `yd resource create`, or `--jsonnet-dry-run`/`-J` to see a Jsonnet file's conversion into JSON:

```shell
yd resource create --dry-run templates.json
```

The printed form leaves out each specification's `resource` property; `--json` keeps it. A dry run still contacts the Platform, to look names up.

The sections below give example specifications for each resource type.

## Keyrings

The Keyring models can be found in the Account API at: https://docs.yellowdog.ai/api?spec=Account%20API.

A Keyring needs a `name` and a `description`:

```json
{"resource": "Keyring", "name": "render-keys", "description": "Keys for the render pipeline"}
```

Two Keyrings at once:

```json
[
  {"resource": "Keyring", "name": "render-keys", "description": "Keys for the render pipeline"},
  {"resource": "Keyring", "name": "test-keys", "description": "Keys for testing"}
]
```

A new Keyring is usable only by the YellowDog Application that created it. The Platform also returns a **system-generated password**, once, which lets YellowDog Portal users claim the Keyring. The password is not displayed unless `--show-keyring-passwords` is given:

```shell
% yd resource create --show-keyring-passwords keyring.json
...
Created Keyring 'render-keys' (ydid:keyring:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa): Password = 4OQAdcZagUX7ZiHaYvqC4yuKb4KCyN9lk4Z7mCcTYXA
...
```

With `--quiet` as well, the command prints the Keyring's ID and its password alone, separated by a space:

```shell
% yd resource create --quiet --show-keyring-passwords keyring.json
ydid:keyring:000000:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa 4OQAdcZagUX7ZiHaYvqC4yuKb4KCyN9lk4Z7mCcTYXA
```

Re-running `yd resource create` on an existing Keyring **updates its description in place**, after confirmation, and leaves its credentials and accessors as they are. The description is the only property the Platform allows to change, and the name is what an existing Keyring is matched on. To recreate a Keyring, for a fresh password say, remove it with `yd resource remove` and create it again, which loses its credentials.

## Credentials

The Credential models can be found in the Account API at: https://docs.yellowdog.ai/api?spec=Account%20API.

To add an AWS credential to a Keyring:

```json
{
  "resource": "Credential",
  "keyringName": "render-keys",
  "credential": {
    "type": "co.yellowdog.platform.account.credentials.AwsCredential",
    "name": "aws-creds",
    "description": "AWS credentials for rendering",
    "accessKeyId": "AKIAIOSFODNN7EXAMPLE",
    "secretAccessKey": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
  }
}
```

To **update** a Credential, edit its specification and run `yd resource create` again. To remove it, run `yd resource remove`.

## Compute Source Templates

The Compute Source Template models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

An example Compute Source Template:

```json
{
  "resource": "ComputeSourceTemplate",
  "namespace": "image-processing",
  "description": "AWS on-demand instances in eu-west-2",
  "attributes": [],
  "source": {
    "type": "co.yellowdog.platform.model.AwsInstancesComputeSource",
    "name": "aws-eu-west-2-ondemand",
    "credential": "render-keys/aws-creds",
    "region": "eu-west-2",
    "securityGroupId": "sg-07bcbfb052873888",
    "instanceType": "*",
    "imageId": "image-processing/ubuntu-render-agent",
    "limit": 0,
    "specifyMinimum": false,
    "assignPublicIp": true,
    "subnetId": "subnet-0d241e541249e9fdc",
    "instanceTags": {"environment": "render-prod"}
  }
}
```

The `imageId` property takes an Image Family's name, **namespace/family-name**, or an Image Group's, **namespace/family-name/group-name**, in place of an ID: `"imageId": "yellowdog/yd-agent-docker"`, for example. `yd resource create` looks the name up and substitutes a well-formed name or ID. A **`yd/`** prefix may also be used.

The `userData` property inside the `source` object takes an inline script. Alternatively, `userDataFile` takes the path of a script file, and `userDataFiles` a list of paths whose contents are concatenated in order.

#### Details

**User Data.** `userData`, `userDataFile` and `userDataFiles` are mutually exclusive. Relative paths are resolved from the directory containing the resource specification file. Variable substitutions using the `__{{variable}}__` syntax are applied to the file contents, as they are to an inline `userData`.

## Compute Requirement Templates

The Compute Requirement Template models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

A **static** template:

```json
{
  "resource": "ComputeRequirementTemplate",
  "imagesId": "ami-097767a3a3e071555",
  "instanceTags": {},
  "name": "render-static",
  "namespace": "image-processing",
  "strategyType": "co.yellowdog.platform.model.WaterfallProvisionStrategy",
  "type": "co.yellowdog.platform.model.ComputeRequirementStaticTemplate",
  "sources": [
    {"instanceType": "t3a.small", "sourceTemplateId": "ydid:cst:D9C548:d41c36a7-0630-4fa2-87e7-4e20bf472bcd"},
    {"instanceType": "t3a.medium", "sourceTemplateId": "image-processing/aws-eu-west-2-ondemand"}
  ]
}
```

A source's `sourceTemplateId` can name its Compute Source Template, as `namespace/compute_source_template_name` or by name alone, in place of its ID. A name alone is looked up in the Compute Requirement Template's own namespace. `yd resource create` looks the IDs up and substitutes them. The Compute Source Templates must already exist.

The `imagesId` property takes an Image Family's name, **namespace/family-name**, or an Image Group's, **namespace/family-name/group-name**, in place of an ID: `"imagesId": "yellowdog/yd-agent-docker/latest"`, for example. `yd resource create` looks the name up and substitutes a well-formed name or ID.

A **dynamic** template:

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
  "name": "render-dynamic",
  "namespace": "image-processing",
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

#### Details

**Image names.** In `imagesId`, a trailing `/latest` is allowed and ignored, naming the Image Family itself. A **`yd/`** prefix may also be used. A source's `imageId` is resolved as a Compute Source Template's is.

**User Data.** The top-level `userData` property takes an inline script. As with Compute Source Templates, `userDataFile` and `userDataFiles` are supported as mutually exclusive alternatives (see [Compute Source Templates](#compute-source-templates)).

## Image Families

The Image Family models can be found in the Image API: https://docs.yellowdog.ai/api?spec=Images%20API.

An Image Family holds Image Groups, which hold Images:

```json
{
  "resource": "MachineImageFamily",
  "access": "PRIVATE",
  "metadataSpecification": {},
  "name": "windows-render-agent",
  "namespace": "image-processing",
  "osType": "WINDOWS",
  "imageGroups": [
    {
      "metadataSpecification": {},
      "name": "v5_0_16",
      "osType": "WINDOWS",
      "images": [
        {
          "metadata": {},
          "name": "win-2022-yd-agent-5_0_16-eu-west-1",
          "osType": "WINDOWS",
          "provider": "AWS",
          "providerImageId": "ami-0cb09e7f49c1eb021",
          "regions": ["eu-west-1"],
          "supportedInstanceTypes": []
        },
        {
          "metadata": {},
          "name": "win-2022-yd-agent-5_0_16-eu-west-2",
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

When an Image Family is updated, its Image Groups and Images are matched to the existing ones by name, so each Image within a Group needs a name of its own.

#### Details

**Renaming removes.** If the name of an Image Group or an Image is changed in the specification, the existing one with the previous name is removed from the Platform, after confirmation (which `--yes` skips), because it is no longer in the specification. To keep it, leave it in the specification and add new ones alongside.

## Configured Worker Pools

The Configured Worker Pool models can be found in the Scheduler API at: https://docs.yellowdog.ai/api?spec=Scheduler%20API. `yd resource create` requires its `namespace`, which the API leaves optional.

```json
{
  "resource": "ConfiguredWorkerPool",
  "name": "render-onprem",
  "namespace": "image-processing",
  "properties": {
    "nodeConfiguration": {
      "nodeTypes": [
        {
          "name": "render-node",
          "min": 1,
          "sourceNames": ["onprem-render"],
          "slotNumbering": "REUSABLE"
        }
      ],
      "nodeEvents": {
        "STARTUP_NODES_ADDED": [
          {"actions": [{"action": "CREATE_WORKERS", "totalWorkers": 1}]}
        ]
      }
    },
    "targetNodeCount": 0
  }
}
```

`yd resource create` reports the pool's token when it creates the pool, and `yd show --show-token` shows it. It can be refreshed or regenerated with [`yd workerpool token`](commands.md#yd-workerpool-token). The token never expires unless `tokenTtl` is given, as an ISO 8601 duration alongside `name` and `namespace` (`"tokenTtl": "PT720H"` for 30 days).

A Configured Worker Pool cannot be updated: `yd resource create` adds a new pool each time. `yd resource remove` shuts the pool down rather than deleting it.

#### Details

**Node types and events.** Each entry in `nodeTypes` gives either a `count` or a `min`, never both, and whichever it gives must be at least 1. An event in `nodeEvents`, if given, must have at least one action group.

**Variables in Node Actions.** The Node Actions in `nodeEvents` are processed by the Platform's own Mustache templating (`{{node.details.hostname}}`, `{{nodesByType.slurmctld.0.details.privateIpAddress}}`). So a CLI variable substitution within them is written `__{{variable}}__`, and a plain `{{...}}` there is left for the Platform (see [Variable Substitutions in Worker Pool and Compute Requirement Specifications, and in User Data](variables.md#variable-substitutions-in-worker-pool-and-compute-requirement-specifications-and-in-user-data)).

**Removing a pool by name.** A pool that has been shut down stays listed under its name, so a name can match several pools. `yd resource remove` shuts down those that have not finished, and leaves the rest.

## Allowances

The Allowance models can be found in the Usage API at: https://docs.yellowdog.ai/api?spec=Usage%20API.

```json
{
  "resource": "Allowance",
  "description": "render-team-monthly",
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

The `effectiveFrom` and `effectiveUntil` dates can use any format the **[dateparser](https://dateparser.readthedocs.io/en/latest/)** library supports, including some natural language. In a TOML resource specification, a TOML date or date-time value can be used as it is. A dry run shows the parsed dates in ISO 8601 form.

A template can be named in place of its ID, and `yd resource create` substitutes the ID: a Compute Source Template in a Sources Allowance's (`co.yellowdog.platform.model.SourcesAllowance`) `sourceCreatedFromId`, and a Compute Requirement Template in a Requirements Allowance's `requirementCreatedFromId`. A name without a namespace is looked up in the configured namespace.

Allowances **cannot be updated** once created; they can only be removed and recreated. To replace an Allowance, give `--match-allowances-by-description`/`-M`, which matches existing Allowances by their `description`:

```shell
yd resource create -M allowance.json
```

`yd resource remove` likewise matches Allowances by `description` only with `-M`. Allowances can also be removed by their IDs (`yd resource remove ydid:allow:000000:9b2f4c1e-5d7a-4e3b-8c6f-1a2b3c4d5e6f`).

Allowances can be **boosted** (have extra hours added) with the `yd allowance boost` command.

#### Details

**Source Allowances.** A Source Allowance (type `co.yellowdog.platform.model.SourceAllowance`) takes the Compute Source ID itself in its `sourceId` property, **not** the Compute Source Template ID.

**Replacing with `-M`.** When matches are found, `yd resource create` asks which ones to remove, selecting from them when there are several (a selection `--yes` does not skip), and asks to confirm each removal, all before the new Allowance is created. The chosen ones are removed once it exists, so a creation that fails leaves the existing ones in place. A run that cannot ask (no terminal to answer from) fails before anything has changed.

**Removing with `-M`.** A specification without a `description` is skipped, with a warning.

## Attribute Definitions

The Attribute Definition models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

### String Attribute Definitions

```json
{
  "resource": "StringAttributeDefinition",
  "name": "user.render-quality",
  "title": "Render quality",
  "description": "The quality a node is set up to render at",
  "options": ["draft", "preview", "final"]
}
```

The `name` and `title` properties are required, and the rest are optional. The `name` must start with `user.`.

### Numeric Attribute Definitions

```json
{
  "resource": "NumericAttributeDefinition",
  "name": "user.max-cost",
  "title": "Maximum cost",
  "defaultRankOrder": "PREFER_LOWER",
  "description": "The most an hour of rendering may cost",
  "units": "$",
  "range": {"min": 1, "max": 10}
}
```

The `name`, `title` and `defaultRankOrder` properties are required, and the rest are optional. Either the `range` property or the `options` property (with numeric option values) can be given, but not both. The `name` must start with `user.`.

## Namespace Policies

```json
{
  "resource": "NamespacePolicy",
  "namespace": "image-processing",
  "autoscalingMaxNodes": 3
}
```

Namespace Policies are matched by their `namespace` property when using `yd resource create` and `yd resource remove`. To remove an existing limit for a namespace, omit `autoscalingMaxNodes` or set it to `null`.

## Groups

A Group can be given a list of roles, each with its scope, and is created or updated with those roles. A role is named by its name or its YellowDog ID.

```json
{
  "resource": "Group",
  "name": "render-team",
  "description": "Everyone running render jobs",
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
          {"namespace": "image-processing"},
          {"namespace": "render-dev"}
        ]
      }
    }
  ]
}
```

#### Details

**Updating roles.** When an existing Group is updated with a `roles` list, the roles it holds that the list does not name are removed, so `"roles": []` removes them all. Without a `roles` property, its roles are left as they are.

**A role that does not exist** fails the Group before anything is changed.

## Applications

An Application can be given a list of Groups to belong to, each named by its name or its YellowDog ID.

```json
{
    "resource": "Application",
    "name": "render-pipeline",
    "description": "Submits the nightly render jobs",
    "groups" : ["render-team"]
}
```

#### Details

**Updating Groups.** When an existing Application is updated with a `groups` list, it is removed from the Groups the list does not name, so `"groups": []` removes it from them all. Without a `groups` property, its Groups are left as they are.

**A Group that does not exist** fails the Application before anything is changed.

### Granting Keyring Access

An optional `keyrings` list grants the Application access to Keyrings, named by their names.

```json
{
    "resource": "Application",
    "name": "render-pipeline",
    "keyrings": ["render-keys", "test-keys"]
}
```

When an Application is **created**, the grant uses the API key the Platform returns at creation, and needs no further options.

When an Application is **updated**, the grant needs the Application's API key, which the Platform returns only when the key is created. So an update with a `keyrings` list is refused unless `--regenerate-app-keys` is given, and the newly generated key is then used for the grant:

```shell
yd resource create --regenerate-app-keys render-pipeline.json
```

A grant that fails (because the Keyring does not exist, for example) fails the Application, after the other Keyrings have been tried.

### Creating and Regenerating Application Keys

When an Application is created, its Application Key ID and Secret are displayed, even with `--quiet`.

When an Application is updated, `--regenerate-app-keys` invalidates its current key and secret, revokes its Keyring access, and generates a new key and secret, which are displayed.

## Users

Users cannot be created or removed with resource specifications, but their Groups can be managed. A Group is named by its name or its YellowDog ID.

**Internal** YellowDog users are identified by their `username`, `name` or `id` properties:

```json
{
  "resource": "InternalUser",
  "username": "jsmith",
  "groups": ["administrators", "render-team"]
}
```

**External** users (users authenticated by an external auth provider) are identified by their `name` or `id` properties:

```json
{
  "resource": "ExternalUser",
  "name": "Jane Smith",
  "groups": ["administrators", "render-team"]
}
```

By YellowDog ID:

```json
{
  "resource": "InternalUser",
  "id": "ydid:user:000000:73c3189e-4e87-4e32-bdbd-8b45e7e9780c",
  "groups": ["administrators", "render-team"]
}
```

#### Details

**Updating Groups.** With a `groups` list, the user is removed from the Groups the list does not name, so `"groups": []` removes them from all of them. Without a `groups` property, their Groups are left as they are.

**Failures.** A user or Group that does not exist fails the specification before anything is changed, as do identifying properties that name different users.

## Namespaces

Namespaces are created and removed with specifications of this form:

```json
{
  "resource": "Namespace",
  "name": "image-processing"
}
```

A namespace cannot be removed if it has ever been populated.
