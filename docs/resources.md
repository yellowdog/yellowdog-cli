# Creating, Updating and Removing YellowDog Resources

<!--ts-->
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

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 10:46:48 BST 2026 -->

<!--te-->


The commands **yd-create** and **yd-remove** allow the creation, update and removal of the following YellowDog resources:

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

The **yd-create** and **yd-remove** commands operate on a list of one or more resource specification files in JSON (or Jsonnet) format.

Each resource specification file can contain a single resource specification or a list of resource specifications. Different resource types can be mixed together in the same list.

The complete list of resource specifications is re-sequenced on processing to ensure that possibly dependent resources are dealt with in a suitable order. For example, all Compute Source Templates are always processed before any Compute Requirement Templates on resource creation, and the reverse sequencing is used on resource removal.

The `--no-resequence` option (`yd-create` only) disables this, processing the resources strictly in the order in which they appear. This is occasionally useful when the supplied order is deliberate and the automatic sequencing would disturb it; note that dependent resources will then fail to be created if they are listed before the resources they depend on.

Resource specification files can use all forms of **variable substitution** just as in the case of Work Requirements, etc.

### Resource Creation

To create resources, use the `yd-create` command as follows:

```shell
yd-create resources_1.json <resources_2.json, ...>
```

### Resource Update

Resources are updated by re-running the `yd-create` command with the same (edited) resource specifications. Update operations will prompt the user for approval: as in other commands, this can be overridden using the `--yes` command-line option.

The update action will create any resources that are not already present in the Platform, and it will update any resources that are already present. The command does not check for specific differences, so an unchanged resource specification will still cause an update.

### Resource Removal

Resources are removed by running the `yd-remove` command, with the same form of resource specifications. For example:

```shell
yd-remove resources_1.json <resources_2.json, ...>
```
Destructive operations will prompt the user for approval: as in other commands, this can be overridden using the `--yes` command-line option.

The `yd-remove` command can also be used to remove resources by their `ydid` resource IDs, by using the `--ids` option: Compute Source and Compute Requirement Templates, Machine Image Families, Image Groups and Images, Keyrings, Allowances, Groups and Applications can be removed, and Worker Pools shut down. Every ID is checked before anything is removed, and one of another type, or anything that is not an ID, is refused; an ID given twice is removed once. Each resource is fetched before it is removed, so one that does not exist is reported, without a prompt, as not found (exit code 6), and a Worker Pool that has already been shut down is skipped. For example:

```shell
yd-remove --ids ydid:crt:D9C548:2a09093d-c74c-4bde-95d1-c576c6f03b13 ydid:imgfam:D9C548:4bc3cc57-1387-49a6-85d4-132bcf3a65fd
```

### Resource Matching

Resources match on **resource names** and (where applicable) **resource namespaces** rather than on YellowDog IDs. This is done for flexibility and to allow the `yd-create` and `yd-remove` commands to be stateless (i.e. we don't need to keep a local record of the YellowDog IDs of the resources created).

However, this means that **caution is required** when updating or removing resources, since resource matching is done using **only** the **namespace/name** of the resource — i.e. the system-generated `ydid` IDs are not used. This means that a resource with a given name could have been removed and replaced in the platform by some other means, and the resource specification(s) would still match it.

## Resource Specification Definitions

The JSON specification used to define each type of resource can be found by inspecting the YellowDog Platform REST API documentation at https://docs.yellowdog.ai/api.

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
- `"InternalUser"`, `"ExternalUser"` (update only)
- `"Namespace"`

## Generating Resource Specifications using `yd-list`

To generate example JSON specifications from resources already included in the platform, the `yd-list` command can be used with the `--details`, `--substitute-ids`/`-U`, and `--strip-ids` options, and select the resources for which details are required. E.g.:

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

Alternatively, the `yd-show` command can be used with one or more `ydid` arguments to generate the details of each identified resource. E.g.:

```shell
yd-show -q ydid:cst:000000:cde265f8-0b17-4e0e-be1c-505174a620e4 --substitute-ids --strip-ids --output-file my-compute-source-template.json
```

would generate a JSON file that can be used with `yd-create` without alteration, or which could be edited.

As illustrated above, both `yd-list` and `yd-show` support the `--substitute-ids`/`-U` option. For Compute Requirement Template detailed output, this will substitute Compute Source Template IDs and Image Family and Group IDs with their names, to make it easier to reuse the outputs. For Compute Source Templates, Image Family and Group IDs will be substituted.

The `--strip-ids` option will remove any YellowDog IDs ('ydids') from the JSON output, as well as any other properties that are not required in order to use the output with `yd-create`.

### Usage Scenario: Moving or Copying Resources to a New Namespace

In the following usage scenario, we want to move a set of resources from one namespace `ns-1`, to another `ns-2`. We'll move all Compute Source Templates, Compute Requirement Templates, and Image Families.

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

Use an editor's search and replace function, or a command-line tool such as `sed` to replace all occurrences of `"ns-1"` with `"ns-2"`, for every `namespace` property, in each of the JSON files.

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

When a new Keyring is created it's usable only by the YellowDog application which created it. A **system-generated password** is also returned as a one-time response, which would allow the Keyring also to be claimed by YellowDog Portal users. For security reasons the password is not displayed, but this behaviour can be overridden using the `--show-keyring-passwords` command-line option, e.g.:

```shell
% yd-create --quiet --show-keyring-passwords keyring.json
Keyring 'my-keyring-1': Password = 4OQAdcZagUX7ZiHaYvqC4yuKb4KCyN9lk4Z7mCcTYXA
```

Re-running `yd-create` on an existing Keyring **updates its description in place**, after confirmation, and leaves its credentials and accessors as they are: the description is the only property the Platform allows to change, and the name is what an existing Keyring is matched on. To recreate a Keyring — for a fresh password, say — remove it with `yd-remove` and create it again, which loses its credentials.

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
    "iamInstanceProfileArn": null,
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

An example Compute Requirement resource specification is found below, for a **static** template:

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

Also, in the `imagesId` property, an Image Family name **namespace/family-name** or an Image Group name **namespace/family-name/group-name** may be used instead of an ID. For example: `"imagesId": "yellowdog/yd-agent-docker/latest"`. The `yd-create` command will look up the Image Family name and substitute with a well-formed name or ID. A **`yd/`** prefix may also optionally be used.

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
          "min": 1,
          "sourceNames": ["example"],
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

Each entry in `nodeTypes` gives either a `count` or a `min`, never both, and whichever it gives must be at least 1; an event in `nodeEvents`, if given, must have at least one action group. The pool's token never expires unless `tokenTtl` is given, as an ISO 8601 duration alongside `name` and `namespace` (`"tokenTtl": "PT720H"` for 30 days). A Configured Worker Pool cannot be updated, and `yd-remove` shuts it down rather than deleting it. Its token, which `yd-create` reports when it creates the pool and `yd-show --show-token` shows, can be refreshed or regenerated with [`yd-token`](commands.md#yd-token). A pool that has been shut down stays listed under its name, so a name can match several pools: `yd-remove` shuts down those that have not finished, and leaves the rest.

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

The `effectiveFrom` and `effectiveUntil` date-time string fields can use any format supported by the **[dateparser](https://dateparser.readthedocs.io/en/latest/)** library, including some natural language formulations. In a TOML resource specification, a TOML date or date-time value can be used as it is. A dry run shows the parsed dates in ISO 8601 form.

Compute Source Template and Compute Requirement Template IDs can use names instead of IDs, and the IDs will be substituted by `yd-create`. However, if a Source allowance is created (type `co.yellowdog.platform.model.SourceAllowance`), then the Compute Source ID (note: **not** the Compute Source Template ID) itself must be used in the `sourceId` property.

Allowances **cannot be updated** (edited) once they have been created; they can only be removed and recreated. However, if using `yd-create` to update existing Allowances, the `--match-allowances-by-description`/`-M` option can be used, in which case Allowances will be matched using their `description` property. If matches are found, the user is asked which ones to remove (selecting from them when there are several, a selection `--yes` does not skip) and to confirm each removal, all before the new Allowance is created; the chosen ones are removed once it exists, so a creation that fails leaves the existing ones in place, and a run that cannot be asked (no terminal to answer from) fails before anything has changed.

When using `yd-remove`, Allowances are again matched using their `description` property only if `--match-allowances-by-description`/`-M` is used; a specification without a `description` is skipped, with a warning. As with other resources, Allowances can also be removed by their IDs (`yd-remove --ids <allowance_id> [<allowance_id>]`).

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

When creating and updating groups, a list of roles with their scopes can be supplied and the group will be created or updated with the roles specified. Roles can be identified by their names or YellowDog IDs. When an existing group is updated with a `roles` list, roles it holds that the list does not name are removed, so `"roles": []` removes them all; without a `roles` property its roles are left as they are. A role that does not exist fails the group before anything is changed.

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

When creating and updating Applications, a list of groups to which the Application should belong can optionally be supplied. Groups can be specified by their names or YellowDog IDs. When an existing Application is updated with a `groups` list, it is removed from groups the list does not name, so `"groups": []` removes it from them all; without a `groups` property its groups are left as they are. A group that does not exist fails the Application before anything is changed.

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

When an Application is **updated**, the grant needs the Application's API key, which the platform returns only when the key is created, so an update with a `keyrings` list is refused unless `--regenerate-app-keys` is used, in which case the newly generated key is used to perform the grant. A grant that fails (for example, because the Keyring does not exist) fails the Application, after the other Keyrings have been tried.

### Creating and Regenerating Application Keys

When an Application is created, its Application Key ID and Secret will be displayed (even if the `--quiet` option is used).

When an Application is updated, the `--regenerate-app-keys` option can be used. This will invalidate the current Application key and secret, revoke any Keyring access, and generate a new key and secret, which will be displayed.

## Users

Users cannot be created or removed using the resource specification approach, but their groups can be managed. Groups can be specified by their names or YellowDog IDs. With a `groups` list, the user is removed from groups the list does not name, so `"groups": []` removes them from all of them; without a `groups` property their groups are left as they are. A user or group that does not exist fails the specification before anything is changed, as do identifying properties that name different users.

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
