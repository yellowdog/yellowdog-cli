# Checking Specifications

<!--ts-->
   * [Checking a File Before Submitting It](#checking-a-file-before-submitting-it)
   * [Every Run Checks Too](#every-run-checks-too)
   * [Schemas for Your Editor](#schemas-for-your-editor)
   * [Keeping the Schemas Current](#keeping-the-schemas-current)
   * [Checking in a Script or CI](#checking-in-a-script-or-ci)
   * [The Compiled-Schema Cache](#the-compiled-schema-cache)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Oct 26 10:19:41 GMT 2026 -->

<!--te-->

Every kind of specification the CLI reads has a JSON Schema describing exactly what it accepts: a Work Requirement (`work-requirement`), a Worker Pool (`worker-pool`), a Compute Requirement (`compute-requirement`), resources (`resources`), Node Actions (`node-actions`), and the TOML configuration file (`config`). Every property the CLI itself defines is described from the CLI's own reference for it, such as the [Work Requirement Property Dictionary](property-dictionary.md); every other property is described from the installed YellowDog SDK. A file can be checked against its schema from the command line, in a script, or in an editor as it is written, and none of these contacts the YellowDog Platform.

## Checking a File Before Submitting It

`--validate` checks a specification against its schema and stops, submitting nothing. It is an option of `yd workrequirement submit`, `yd workerpool provision`, `yd computerequirement instantiate`, `yd resource create` and `yd node action`:

```shell
% yd workrequirement submit wr.json --validate
Loading Work Requirement data from: 'wr.json'
ERROR : 'wr.json': taskGroups[0].taskCount: must be integer or null
ERROR : 'wr.json': (document): unknown property 'priorty'
```

Every violation is reported, each with where in the file it is (`(document)` is the top level), and the command exits 1. A valid file is reported as such, with exit code 0:

```shell
% yd workrequirement submit ok.json --validate
Loading Work Requirement data from: 'ok.json'
'ok.json': valid against the work-requirement schema
```

With `--json`, the result is the array of violations, `[]` for a valid file:

```shell
% yd resource create keyring.json --validate --json
[
  {"source": "keyring.json", "path": "(document)", "message": "missing required property 'description'"}
]
```

The file is checked as the command would use it: after its `{{variable}}` substitutions, after Jsonnet or TOML has been converted to JSON, and after any CSV expansion. `--validate` is refused where there is no specification file to check: a Work Requirement or Worker Pool built from the configuration file alone, `yd workrequirement submit --json-raw` (whose file is the Platform's own JSON) and `yd node action --status`.

Although it contacts nothing, `--validate` runs as the rest of the command does, which needs an Application key and secret to be configured (exit 3 without them). On a machine with none, such as a CI job, any values will do: `YD_KEY=x YD_SECRET=x yd workrequirement submit wr.json --validate`.

## Every Run Checks Too

Every run of those five commands checks its specification the same way, and warns of each violation without stopping: the Platform, or the CLI's own processing, still has the final say on whether the specification is accepted. Every command also checks the configuration file against the `config` schema as it starts (see [Configuration](configuration.md)), unless `--quiet` is given.

If a schema cannot be built from the installed SDK (a newer SDK with a property the CLI cannot yet describe), the run warns once that the file went unchecked and carries on as it would without a schema; `yd schema <family>` shows why.

## Schemas for Your Editor

`yd schema --write <dir>` writes every schema to a directory, one file per family, for an editor to check files against as they are written:

```shell
% yd schema --write schemas
wrote schemas/work-requirement.schema.json
wrote schemas/worker-pool.schema.json
wrote schemas/compute-requirement.schema.json
wrote schemas/resources.schema.json
wrote schemas/node-actions.schema.json
wrote schemas/config.schema.json
wrote schemas/index.json
```

In VS Code, map the files to the schemas in `settings.json`, by whatever naming convention your files follow, for example:

```json
"json.schemas": [
  {"fileMatch": ["*.wr.json"], "url": "./schemas/work-requirement.schema.json"},
  {"fileMatch": ["*.wp.json"], "url": "./schemas/worker-pool.schema.json"},
  {"fileMatch": ["*.cr.json"], "url": "./schemas/compute-requirement.schema.json"},
  {"fileMatch": ["*.resources.json"], "url": "./schemas/resources.schema.json"},
  {"fileMatch": ["*.actions.json"], "url": "./schemas/node-actions.schema.json"}
]
```

JetBrains IDEs offer the same under Preferences → Languages & Frameworks → Schemas and DTDs → JSON Schema Mappings.

Alternatively, a file can name its own schema with a `$schema` key at the top, which the CLI accepts and removes, so it is never sent on to the Platform:

```json
{
  "$schema": "./schemas/work-requirement.schema.json",
  "taskType": "bash",
  "taskGroups": [{"tasks": [{"arguments": ["-c", "echo hello"]}]}]
}
```

The configuration file can do the same, with a top-level `"$schema" = "./schemas/config.schema.json"`, which the configuration check accepts; editors whose TOML support comes from Taplo (such as VS Code's Even Better TOML) also read a `#:schema ./schemas/config.schema.json` comment on the first line, which the CLI ignores as it does any comment.

An editor checks the file as written, while the CLI checks it after substitution and conversion. A `{{variable}}` is accepted wherever a value stands, so an unresolved one is never itself a violation; but a resource's `resource` property and a Node Action's `type` choose which further properties are checked, so a `{{variable}}` there leaves the rest of that resource or action unchecked. An editor cannot check a Jsonnet file against a JSON Schema; run `yd jsonnet2json` on it to see the JSON that is checked.

## Keeping the Schemas Current

The schemas are built from the installed CLI and SDK, so upgrading either can change them. `yd schema --check <dir>` says whether a directory written earlier still matches, comparing the versions in its `index.json` and every family's file with what is installed now:

```shell
% yd schema --check schemas
up to date: CLI 15.2.0, SDK 15.9.1
```

It exits 0 when the directory is up to date and 1 otherwise, naming what differs; `yd schema --write <dir>` again refreshes it. `yd schema <family>` prints one family's schema, and `yd schema --list` lists the families (see [yd schema](commands.md#yd-schema)).

## Checking in a Script or CI

`--validate`'s exit code makes it a check a script can rely on. For example, to check every Work Requirement specification in a directory, carrying on past a failure and failing at the end if any did:

```bash
export YD_KEY=x YD_SECRET=x   # no Platform is contacted; any values will do
failed=0
for f in specs/*.wr.json; do
    yd workrequirement submit "$f" --validate --quiet || failed=1
done
exit $failed
```

`--quiet` leaves the violations, which are errors, and drops the rest. For a report a script can read, add `--json` and collect each file's array.

## The Compiled-Schema Cache

To keep the check quick, each schema is compiled once and kept, a file of up to about 1MB per schema, in a directory of your own under the system's temporary directory (`yellowdog-cli-schemas-<uid>`, or `yellowdog-cli-schemas` on Windows), where the operating system's routine clean-up removes it. It is compiled again whenever the CLI or the SDK changes, and deleting the directory is always safe. If the directory cannot be used (e.g., it is open to other users), the schemas are compiled on every run instead, and `--debug` says why.
