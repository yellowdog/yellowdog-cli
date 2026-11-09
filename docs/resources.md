# Creating, Updating and Removing YellowDog Resources

<!--ts-->
   * [Overview of Operation](#overview-of-operation)
         * [Details](#details)
      * [Resource Creation](#resource-creation)
      * [Resource Update](#resource-update)
         * [Details](#details-1)
      * [Seeing What a Run Would Change](#seeing-what-a-run-would-change)
         * [Details](#details-2)
      * [Resource Removal](#resource-removal)
         * [Details](#details-3)
      * [Resource Matching](#resource-matching)
   * [Resource Specification Definitions](#resource-specification-definitions)
   * [Exporting Resources as Specifications](#exporting-resources-as-specifications)
         * [Details](#details-4)
      * [Usage Scenario: Moving or Copying Resources to a New Namespace](#usage-scenario-moving-or-copying-resources-to-a-new-namespace)
      * [Taking Resources One at a Time with yd list or yd show](#taking-resources-one-at-a-time-with-yd-list-or-yd-show)
   * [Specifying a Resource on the Command Line](#specifying-a-resource-on-the-command-line)
         * [Details](#details-5)
   * [Preprocessing Resource Specifications](#preprocessing-resource-specifications)
   * [Keyrings](#keyrings)
   * [Credentials](#credentials)
   * [Compute Source Templates](#compute-source-templates)
         * [Details](#details-6)
   * [Compute Requirement Templates](#compute-requirement-templates)
         * [Details](#details-7)
   * [Image Families](#image-families)
         * [Details](#details-8)
   * [Configured Worker Pools](#configured-worker-pools)
         * [Details](#details-9)
   * [Allowances](#allowances)
         * [Details](#details-10)
   * [Attribute Definitions](#attribute-definitions)
      * [String Attribute Definitions](#string-attribute-definitions)
      * [Numeric Attribute Definitions](#numeric-attribute-definitions)
   * [Namespace Policies](#namespace-policies)
   * [Groups](#groups)
         * [Details](#details-11)
   * [Applications](#applications)
         * [Details](#details-12)
      * [Granting Keyring Access](#granting-keyring-access)
      * [Creating and Regenerating Application Keys](#creating-and-regenerating-application-keys)
   * [Users](#users)
         * [Details](#details-13)
   * [Namespaces](#namespaces)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Nov  9 16:03:55 GMT 2026 -->

<!--te-->


The commands **yd resource create** and **yd resource remove** create, update and remove YellowDog resources from specification files, and **yd resource plan** shows what a create would change. For example, to create a Keyring, write its specification to `keyring.json`:

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

**Create or update.** A resource not already present in the Platform is created, and one that is present is updated. The command does not check for differences, so an unchanged resource specification still causes an update. `yd resource plan` shows the differences first (see [Seeing What a Run Would Change](#seeing-what-a-run-would-change)).

**Exceptions.** Four resource types behave differently:

- A **Credential** is put into its Keyring, replacing one of the same name, without a prompt.
- A **Namespace** that already exists is reported with a warning and skipped.
- An **Allowance** is created again, as a second Allowance. With `--match-allowances-by-description`/`-M`, it replaces those with the same description instead (see [Allowances](#allowances)).
- A **Configured Worker Pool** is always created as a new pool, never updated. The Platform refuses one whose name is already taken by a Worker Pool in its namespace.

### Seeing What a Run Would Change

To see what `yd resource create` would do before running it, give `yd resource plan` the same files. It changes nothing and asks nothing, and says for each specification whether its resource would be created, updated (with each property that changes), left unchanged, or can't be compared:

```shell
yd resource plan templates.jsonnet
```

```
2026-11-09 12:09:24 : Including 2 resources from 'templates.jsonnet'
2026-11-09 12:09:24 : Plan for 2 resource specifications
2026-11-09 12:09:24 : Unchanged  Compute Source Template 'image-processing/aws-ondemand' (ydid:cst:...:a8cc042e)
2026-11-09 12:09:24 : Changed    Compute Requirement Template 'image-processing/aws-static' (ydid:crt:...:15552169)
                                 description: 'AWS static' → 'AWS static, two sources'
2026-11-09 12:09:24 : 1 changed, 1 unchanged
2026-11-09 12:09:24 : Done
```

Then run `yd resource create` with the same files to make those changes. In a CI job, `--fail-on-changes` makes a plan with anything to do exit 1:

```shell
yd resource plan --fail-on-changes resources/*.jsonnet
```

#### Details

**How each change is shown.** A changed property is shown by its path, with its old and new values: `sources[0].instanceType: 't3.small' → 't3.medium'`. A property the specification no longer sets is shown as `(cleared; was ...)`, because an update replaces the whole resource. A member added to or removed from a list matched by name is shown as `+` or `-`. User Data is shown by its length, and a long string is cut short.

**The four outcomes.** `New` and `Changed` are what the real run would do: create the resource, or update it with the changes listed under it. `Unchanged` means the real run would send what the Platform already holds. `Unknown` is given to a Credential that already exists, since its secrets can't be read back: the real run replaces it. Under `--json` the same outcomes are the records' `action`: `create`, `update`, `unchanged` and `unknown`.

**Namespaces.** Each specification is looked up as `yd resource create` looks it up. Compute Source Templates, Compute Requirement Templates, Image Families, Configured Worker Pools and Namespace Policies are looked up by name in the specification's own `namespace`, usually filled in from the configured namespace through `{{namespace}}`. Keyrings, Credentials, Groups, Applications, Users, Attribute Definitions and Namespaces are found by name across the account.

**Per resource type:**

- A **Compute Source Template** or **Compute Requirement Template** is compared property by property, a Requirement Template's `sources` by position. A source type change is one change, at `source.type`.
- A **Keyring** is compared by its `description` alone, the only property an update changes.
- An **Image Family** is compared with its Image Groups, and the Images in each, matched by name. A removed Image Group is shown as removed, which the real run asks about.
- A **Configured Worker Pool** or an **Allowance** is always `New`, since neither is ever updated. A Configured Worker Pool whose name a Worker Pool in its namespace already holds, even one shut down, fails, as the real run does, since the Platform refuses it. With `--match-allowances-by-description`/`-M`, an Allowance's line lists the Allowances it would replace.
- A **String** or **Numeric Attribute Definition** is compared by the properties its specification sets.
- A **Group** is compared by its `description`, and, when the specification gives `roles`, by the roles added and removed in each scope.
- An **Application** is compared by its `description` and, when the specification gives `groups`, by the Groups it joins and leaves. With `--regenerate-app-keys`, its line says the key would be regenerated, never showing a key.
- A **User** is compared by the Groups it joins and leaves, when the specification gives `groups`. A User not found fails, as the real run does.
- A **Namespace** is `Unchanged` when it exists, and a **Namespace Policy** is compared by its `autoscalingMaxNodes`.
- A **Credential** is `New` when its Keyring holds none of its name, and otherwise `Unknown`. Its line names its Keyring: `Credential 'aws' in Keyring 'cloud-credentials'`.

**References between specifications.** A specification that refers to a resource an earlier specification would create, such as a Requirement Template naming a new Source Template, shows the reference as `(to be created)`. A reference to a resource that neither exists nor is planned fails that specification, as it fails the real run.

**Failures and exit codes.** A specification that can't be planned, for a missing property or an unknown image, for example, is reported as failed, and the rest are still planned; the command then exits with the failures' exit code. An authentication or connection failure stops the plan. Without `--fail-on-changes`, a plan with changes exits 0. Under `--json`, the plan is an array of records (see [Machine-readable Output and Exit Codes](json-output.md)).

**Properties the Platform fills in.** The Platform sets some properties a specification leaves out, such as a Compute Requirement Template's `instanceTags`, which it sets to an empty map. The plan knows these, and doesn't show them as cleared.

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

## Exporting Resources as Specifications

To capture resources already on the Platform as specifications, to keep them under version control, review them, or create them again in another namespace or account, use `yd resource export`. With no types named, it writes the namespace's Compute Source Templates, Compute Requirement Templates, Image Families and Namespace Policy to one file:

```shell
yd resource export --namespace image-processing -o image-processing.jsonnet
```

The file is what `yd resource create` reads, each reference to another resource written as its name. Planning it against the account it came from shows every resource unchanged:

```shell
yd resource plan image-processing.jsonnet
```

To export other types, name them, or give `--all` for every type. `--name` takes a glob pattern, and `--with-dependencies` adds the resources the selected ones refer to, such as a Compute Requirement Template's Compute Source Templates and Image Families. Without `-o`, standard output holds the specifications alone:

```shell
yd resource export keyrings groups applications -o access.json
yd resource export compute-requirement-templates --name 'render-*' --with-dependencies > render.json
```

#### Details

**Which resources are exported.** With no types named, export takes the namespace's Compute Source Templates, Compute Requirement Templates, Image Families and Namespace Policy, and warns that the account-wide types were left out. The account-wide types (Namespaces, Keyrings, Attribute Definitions, Groups, Applications, Users and Allowances) are exported when named or with `--all`. Configured Worker Pools are exported when named or with `--all`. Credentials are exported only when named or with `--include-credentials`, never with `--all` alone. YellowDog's public Image Families are never exported. A type can be given in any case, in the singular (`keyring`, `image-family`), as the resource name a specification uses (`Keyring`, `ComputeSourceTemplate`) or as an unambiguous prefix (`key` for `keyrings`), and `--all` cannot be given with types. The namespace must not be empty: an empty `-n` is refused, and so is an empty configured namespace when a namespaced type is exported.

**Matching by name.** `--name` matches each type's name without its namespace: a glob with no wildcards is an exact match. An Allowance, which has no name, is matched by its description, a Namespace Policy by its namespace, a Credential by its Keyring's name, and a User by its `name`, an Internal User's included. A pattern naming a namespace (`'render/*'`) is refused: give the namespace with `-n`, which takes no pattern either. `--interactive`/`-i` lists the resources of each type, after the filters, to pick from.

**How references are written.** Every reference is written as a name: a Compute Source Template as `namespace/name`, and an Image Family in a namespace of your own as `yd/<namespace>/<family>`. A reference to one of YellowDog's public Image Families is kept as it is and never followed by `--with-dependencies`, which reads each Image Family it would follow by name, once, to tell; an export without it reads none. A reference that cannot be named, such as one to a deleted resource, is written as its ID, with a warning.

**Values holding `{{...}}`.** A value on the Platform holding `{{...}}`, such as User Data with a template in it, is written as a `{{raw:...}}` literal, so that `yd resource create` reads back the value exactly as it was, with nothing substituted (see [Variable Substitution](variables.md)).

**What is left out.** Nothing the Platform assigns is written, an ID included. A property at the value the Platform gives it when a specification leaves it out is left out too, so the file holds what someone chose.

**Applications' Keyring access.** An Application is written with its Groups but without its Keyring access, with a warning naming it. Granting access to an existing Application needs `yd resource create --regenerate-app-keys`, so add `keyrings` to its specification by hand when that is what you want.

**Credentials.** The Platform returns a Credential's name, description and type, but none of its other fields. Each of its required fields other than its name and description, such as an AWS Credential's `accessKeyId` and `secretAccessKey` or an Azure Credential's `clientId`, is written as a variable, named `<keyring>_<credential>_<field>` (lower case, each character other than a letter, digit or `_` written as `_`), and a warning lists the variables. Where two Credentials would give a variable the same name (Keyring `aws-keys` with Credential `prod`, and Keyring `aws` with Credential `keys-prod`), the variable of the later by `keyring/credential` name is numbered (`aws_keys_prod_accesskeyid_2`), and its warning says so. Supply the variables with `-v` or `YD_VAR_*` when creating the resources:

```shell
yd resource export credentials --name render-keys -o credentials.json
yd resource create credentials.json -v render_keys_aws_creds_accesskeyid=AKIAIOSFODNN7EXAMPLE -v render_keys_aws_creds_secretaccesskey=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

**Dependencies.** `--with-dependencies` follows a Compute Requirement Template's Compute Source Templates and Image Families, a Compute Source Template's Image Family, an Allowance's template, a Credential's Keyring, and an Application's or a User's Groups, transitively, each resource once. Without it, references stay names that `yd resource create` looks up on the Platform.

**The round trip.** `yd resource plan` of an export, against the account it came from, shows every resource `Unchanged`, with three exceptions: a Credential is `Unknown`, its secrets not being comparable; an Allowance is `New`, Allowances never being updated; and a Configured Worker Pool fails, since the Platform refuses a pool whose name is taken.

**Output.** The specifications are one JSON array, in the order `yd resource create` processes them and then by name, so two exports of the same resources are identical and an export can be compared with an earlier one. A `.jsonnet` file is written in the Jsonnet style. Without `-o`, standard output holds only the array, and messages and warnings go to standard error, so `yd resource export > setup.json` needs no `--quiet`. An export that finds nothing writes `[]`, with a warning, and exits 0.

**Failures.** Everything is read before anything is written. A resource that can't be read, for a missing permission for example, is reported and left out, the rest are written, and the command exits with that failure's exit code. An authentication or connection failure writes nothing, leaving an existing file of that name as it was. Under `--json` with `-o`, a record per resource says whether it was exported or skipped (see [Machine-readable Output and Exit Codes](json-output.md)).

### Usage Scenario: Moving or Copying Resources to a New Namespace

In this scenario, a set of resources is moved from the namespace `render-dev` to `render-prod`: all its Compute Source Templates, Compute Requirement Templates and Image Families.

**Step 1: Export the resources to a file**

```shell
yd resource export compute-source-templates compute-requirement-templates image-families --namespace render-dev -o render.json
```

**Step 2: Remove the resources** if moving them

This removes every resource in the file **without asking for confirmation**. To **copy** the resources to the new namespace rather than move them, skip this step.

```shell
yd resource remove -y render.json
```

**Step 3: Change the namespace in the file**

Replace the namespace wherever the file names it. That is every `namespace` property (`"render-dev"`), and the references, which name a resource by its namespace: a Compute Requirement Template's sources (`"render-dev/aws-eu-west-2-ondemand"`) and an Image Family (`"yd/render-dev/ubuntu-render-agent"`). A reference left unchanged would point at the resource removed in step 2. With `sed`, for example:

```shell
sed -i.bak -e 's#"render-dev"#"render-prod"#g' -e 's#"render-dev/#"render-prod/#g' -e 's#"yd/render-dev/#"yd/render-prod/#g' render.json
```

**Step 4: Create the resources in the new namespace**

```shell
yd resource create -y render.json
```

Once the resources have been created, the file can be deleted, or kept for your records.

### Taking Resources One at a Time with `yd list` or `yd show`

`yd list` and `yd show` give a resource's details as a specification too, which suits taking one resource, or a few picked from a listing. Use `yd list` with `--details`, `--substitute-ids`/`-U` and `--strip-ids`, and select the resources wanted:

```shell
yd list compute-source-templates --details --substitute-ids --strip-ids
```

The `--output-file` option writes the detailed list to a file instead of displaying it. A file named `.jsonnet` is written in the Jsonnet style, for editing by hand as a [Jsonnet](jsonnet.md) specification: keys unquoted, strings in single quotes and a trailing comma after each last element. It evaluates to the same JSON, so `yd resource create` takes it as it is:

```shell
yd list compute-source-templates --details --substitute-ids --strip-ids --output-file render-templates.jsonnet
```

`yd show` gives the details of each resource whose `ydid` it is given:

```shell
yd show ydid:cst:000000:cde265f8-0b17-4e0e-be1c-505174a620e4 --substitute-ids --strip-ids --output-file aws-eu-west-2-ondemand.json
```

Both `yd list` and `yd show` take these two options:

- `--substitute-ids`/`-U` replaces IDs with names, to make the output easier to reuse. In a Compute Requirement Template, it replaces Compute Source Template IDs and Image Family and Group IDs. In a Compute Source Template, it replaces Image Family and Group IDs.
- `--strip-ids` removes the YellowDog IDs ('ydids') from the JSON output, as well as any other properties not needed to use the output with `yd resource create`.

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

To see the processed JSON without creating or updating anything, use `--dry-run`/`-D` with `yd resource create`, or `--jsonnet-dry-run`/`-J` to see a Jsonnet file as evaluated, its variables substituted:

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

The `imageId` property takes an Image Family's name, **namespace/family-name**, or an Image Group's, **namespace/family-name/group-name**, in place of an ID: `"imageId": "image-processing/ubuntu-render-agent"`, for example. `yd resource create` looks the name up and substitutes a well-formed name or ID. A **`yd/`** prefix may also be used.

The image must run the YellowDog Agent. YellowDog provides no stock images: use an image of your own with the Agent installed, or a stock operating system image with the [Agent installer](https://github.com/yellowdog/resources/blob/main/agent-install/linux/README.md) as the source's User Data.

The `userData` property inside the `source` object takes an inline script. Alternatively, `userDataFile` takes the path of a script file, and `userDataFiles` a list of paths whose contents are concatenated in order.

#### Details

**User Data.** `userData`, `userDataFile` and `userDataFiles` are mutually exclusive. Relative paths are resolved from the directory containing the resource specification file. Variable substitutions using the `__{{variable}}__` syntax are applied to the file contents, as they are to an inline `userData`.

## Compute Requirement Templates

The Compute Requirement Template models can be found in the Compute API at: https://docs.yellowdog.ai/api?spec=Compute%20API.

A **static** template:

```json
{
  "resource": "ComputeRequirementTemplate",
  "imagesId": "image-processing/ubuntu-render-agent",
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

The `imagesId` property takes an Image Family's name, **namespace/family-name**, or an Image Group's, **namespace/family-name/group-name**, in place of an ID: `"imagesId": "image-processing/ubuntu-render-agent/latest"`, for example. `yd resource create` looks the name up and substitutes a well-formed name or ID.

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
