# Data Client

<!--ts-->
   * [Named Profiles](#named-profiles)
   * [Variable Substitutions for Data Client Properties](#variable-substitutions-for-data-client-properties)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 09:37:22 BST 2026 -->

<!--te-->


The `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy` commands provide direct access to remote data stores (object storage buckets) via **[rclone](https://rclone.org)**. They do **not** require a YellowDog Application key or secret — only the data store connection details.

This section describes the configuration shared by all five commands; each command is documented individually in the Command List, under [yd-upload](commands.md#yd-upload), [yd-download](commands.md#yd-download), [yd-delete](commands.md#yd-delete), [yd-ls](commands.md#yd-ls), and [yd-copy](commands.md#yd-copy).

The `rclone` binary will be automatically downloaded if not already present.

These commands share a common `[dataClient]` TOML configuration section:

```toml
[dataClient]
    remote = "myremote"               # rclone remote name (from rclone.conf) or inline connection string
    bucket = "my-bucket"              # bucket / container / root path (see note below)
    prefix = "{{namespace}}/{{tag}}"  # path prefix within the bucket (default: namespace/tag)
```

The `remote`, `bucket`, and `prefix` values can also be supplied via command-line options (`--remote`/`-r`, `--bucket`/`-b`, `--prefix`/`-p`) or environment variables (`YD_DATA_CLIENT_REMOTE`, `YD_DATA_CLIENT_BUCKET`, `YD_DATA_CLIENT_PREFIX`). The `--no-prefix` flag disables the prefix entirely.

The `remote` field accepts either:
- A plain remote name defined in the system `rclone.conf` (e.g. `"yds3"`)
- An inline rclone connection string (e.g. `"S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2"`), or rclone's own form, `":s3,provider=AWS,env_auth=true,region=eu-west-2"`, whose backend is its type
- An `rclone:` prefix can optionally be included

A value in an inline connection string is read as rclone reads it: one holding a comma goes in double or single quotes (`secret_access_key="a,b"`), a quote inside it doubled, and spaces around `=` are allowed.

The default prefix is `{{namespace}}/{{tag}}`, using the `namespace` and `tag` values from the `[common]` section (or their environment variable / command-line equivalents). Variable substitutions (`{{...}}`) are supported in all `[dataClient]` values and also in the remote path arguments passed to `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy` on the command line. All built-in variables (`{{namespace}}`, `{{tag}}`, `{{username}}`, `{{date}}`, etc.) and user-defined variables (`YD_VAR_*` / `[common.variables]`) are available. Arguments containing `{{...}}` should be quoted to prevent shell interpretation.

> **Note on `bucket`:** The `bucket` property is named after S3/GCS terminology but applies equally to other rclone storage backends — use it to specify the container name (Azure Blob Storage), the root directory (SFTP, local, Google Drive), or the equivalent top-level path component for your storage target. A root directory beginning with `/` (`bucket = "/data/results"`) is an absolute path, and is kept as one; without the `/` it is relative to the remote's default directory (for a local remote, the current directory). With no bucket, the same holds for a prefix beginning with `/`.

## Named Profiles

Multiple named profiles can be defined as sub-tables of `[dataClient]`. A named profile overrides only the fields it specifies; any field not set in the profile inherits the corresponding value from the base `[dataClient]` section.

```toml
[dataClient]
prefix = "{{namespace}}/{{tag}}"   # shared default inherited by all profiles

[dataClient.prod]
remote = "s3-prod"
bucket = "prod-data"

[dataClient.staging]
remote = "s3-staging"
bucket = "staging-data"
# inherits prefix from [dataClient]
```

Select a profile with `--data-client-profile <name>`:

```
yd-upload --data-client-profile prod myfile.txt
yd-download --data-client-profile staging results/
```

The active profile can also be set via the `YD_DATA_CLIENT` environment variable. The `--remote`, `--bucket`, `--prefix`, and `--no-prefix` flags still apply on top of the selected profile, so individual fields can be overridden per invocation.

Profile names are free-form; the only reserved names are `remote`, `bucket`, and `prefix` (the scalar field names of `[dataClient]` itself). A profile takes only those three keys: any other, such as a misspelt `bukcet`, is an error, as an unknown key elsewhere in the file is, rather than being ignored while the profile uses the base section's value.

## Variable Substitutions for Data Client Properties

The `remote`, `bucket`, and `prefix` values from `[dataClient]` are available as variable substitutions in all spec files (TOML, JSON, Jsonnet) and in `userdata` scripts for every command — including `yd-submit`, `yd-provision`, and `yd-instantiate`:

| Variable | Value |
|---|---|
| `{{dataClient.remote}}` | Active profile's remote (or base `[dataClient].remote`) |
| `{{dataClient.bucket}}` | Active profile's bucket |
| `{{dataClient.prefix}}` | Active profile's prefix |
| `{{dataClient.<name>.remote}}` | Named profile's remote, regardless of active selection |
| `{{dataClient.<name>.bucket}}` | Named profile's bucket |
| `{{dataClient.<name>.prefix}}` | Named profile's prefix |

For `yd-upload`/`yd-download`/`yd-delete`/`yd-ls`/`yd-copy`, `{{dataClient.remote/bucket/prefix}}` reflects the fully resolved active source profile (after `--data-client-profile` selection, env vars, and CLI overrides). For all other commands, it reflects the base `[dataClient]` section.

Named profile variables are always resolved with profile fields taking precedence over the base section, so `{{dataClient.prod.prefix}}` gives the prod profile's prefix (or the base prefix if not set in `[dataClient.prod]`).

> **Note on Worker Pool / Compute Requirement specs and User Data:** In JSON/Jsonnet Worker Pool and Compute Requirement specifications, and in all User Data (whether supplied via `userData`, `userDataFile`, or `userDataFiles`), variable substitutions **must be prefixed and postfixed by double underscores** to disambiguate them from server-side Mustache processing. Use `__{{dataClient.remote}}__`, `__{{dataClient.prod.bucket}}__`, etc.

Example use in a Work Requirement spec (no underscores needed in WR JSON):

```json
{
  "taskDataInputs": [
    {
      "source": "{{dataClient.remote}}:{{dataClient.bucket}}/{{dataClient.prefix}}/input.csv",
      "destination": "input.csv"
    }
  ]
}
```

Example use in a `userdata` script (double underscores required):

```bash
#!/bin/bash
rclone copy __{{dataClient.prod.remote}}__:__{{dataClient.prod.bucket}}__/configs /tmp/configs
```
