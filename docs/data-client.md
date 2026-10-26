# Data Client

<!--ts-->
   * [Remote Paths](#remote-paths)
   * [Named Profiles](#named-profiles)
   * [Variable Substitutions for Data Client Properties](#variable-substitutions-for-data-client-properties)
   * [Worked Examples](#worked-examples)
      * [Trying It Out on Your Own Machine](#trying-it-out-on-your-own-machine)
      * [Amazon S3](#amazon-s3)
      * [An SFTP Server, Named in rclone.conf](#an-sftp-server-named-in-rcloneconf)
      * [Several Stores, One Configuration](#several-stores-one-configuration)
   * [Troubleshooting](#troubleshooting)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Oct 26 10:06:03 GMT 2026 -->

<!--te-->


The `yd data upload`, `yd data download`, `yd data delete`, `yd data list`, and `yd data copy` commands provide direct access to remote data stores (object storage buckets) via **[rclone](https://rclone.org)**. They do **not** require a YellowDog Application key or secret — only the data store connection details.

This section describes the configuration shared by all five commands; each command is documented individually in the Command List, under [yd data upload](commands.md#yd-data-upload), [yd data download](commands.md#yd-data-download), [yd data delete](commands.md#yd-data-delete), [yd data list](commands.md#yd-data-list), and [yd data copy](commands.md#yd-data-copy).

The commands run `rclone`: one already on your `PATH` is used in preference and never modified; otherwise the binary is downloaded the first time it is needed, into `rclone_api`'s own per-user cache directory (`~/Library/Caches/rclone_api` on macOS, `~/.cache/rclone_api` on Linux, and under `%LOCALAPPDATA%` on Windows). Every `yd data` verb takes `--which-rclone`, which reports the binary in use and its version, and `--upgrade-rclone`, which downloads the latest into the cache; each then exits.

These commands share a common `[dataClient]` TOML configuration section:

```toml
[dataClient]
    remote = "myremote"               # rclone remote name (from rclone.conf) or inline connection string
    bucket = "my-bucket"              # bucket / container / root path (see note below)
    prefix = "{{namespace}}/{{tag}}"  # path prefix within the bucket (default: namespace/tag)
```

The `remote`, `bucket`, and `prefix` values can also be supplied via command-line options (`--remote`/`-r`, `--bucket`/`-b`, `--prefix`/`-p`) or environment variables (`YD_DATA_CLIENT_REMOTE`, `YD_DATA_CLIENT_BUCKET`, `YD_DATA_CLIENT_PREFIX`). The `--no-prefix` flag disables the prefix entirely. A `--property dataClient.<key>=<value>` override (or `dataClient.<profile>.<key>`) is a command-line value too, taking precedence over the environment variable. As for the rest of the configuration, a file chosen with `--config`/`-c` takes precedence over the environment variables, though not over the command line (see [Which Value Wins](configuration.md#which-value-wins) for the whole order).

The `remote` field accepts either:
- A plain remote name defined in the system `rclone.conf` (e.g. `"yds3"`)
- An inline rclone connection string (e.g. `"S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2"`), or rclone's own form, `":s3,provider=AWS,env_auth=true,region=eu-west-2"`, whose backend is its type
- An `rclone:` prefix can optionally be included

A remote name is looked up in rclone's configuration file: the one the `RCLONE_CONFIG` environment variable names, else `~/.config/rclone/rclone.conf` (`%APPDATA%\rclone\rclone.conf` on Windows); if there is none, the command says so.

An inline connection string carries whatever credentials it is given in its parameters, so in a `config.toml` it puts them in the file: prefer `env_auth=true` (the cloud provider's own credentials, from the environment or the instance), or a named remote in `rclone.conf`. `yd variables` and `yd doctor` show an inline string's name, type and provider only, withholding its other parameters as `<N parameters redacted>`.

A value in an inline connection string is read as rclone reads it: one holding a comma goes in double or single quotes (`secret_access_key="a,b"`), a quote inside it doubled, and spaces around `=` are allowed.

The default prefix is `{{namespace}}/{{tag}}`, using the `namespace` and `tag` values from the `[common]` section (or their environment variable / command-line equivalents). Variable substitutions (`{{...}}`) are supported in all `[dataClient]` values and also in the remote path arguments passed to `yd data upload`, `yd data download`, `yd data delete`, `yd data list`, and `yd data copy` on the command line. All built-in variables (`{{namespace}}`, `{{tag}}`, `{{username}}`, `{{date}}`, etc.) and user-defined variables (`YD_VAR_*` / `[common.variables]`) are available. Arguments containing `{{...}}` should be quoted to prevent shell interpretation.

> **Note on `bucket`:** The `bucket` property is named after S3/GCS terminology but applies equally to other rclone storage backends — use it to specify the container name (Azure Blob Storage), the root directory (SFTP, local, Google Drive), or the equivalent top-level path component for your storage target. A root directory beginning with `/` (`bucket = "/data/results"`) is an absolute path, and is kept as one; without the `/` it is relative to the remote's default directory (for a local remote, the current directory). With no bucket, the same holds for a prefix beginning with `/`.

> **Note on servers that limit connections:** The `yd data` commands copy up to 128 files at a time, which on cloud object storage (S3, Google Cloud Storage, Azure Blob Storage) is what makes many small files quick. On an SFTP or FTP server, each of those can be a connection of its own, and a server that limits how many connections it accepts at once (OpenSSH's `MaxStartups`, an FTP server's per-user or per-IP limit) refuses the rest. rclone retries a refused connection, so the transfer usually completes, more slowly, but it can fail, and a server that bans an address for repeated dropped connections may ban yours. Cap the connections in the remote itself: `connections` for SFTP (`":sftp,host=files.example.com,user=me,connections=8"`, or `connections = 8` in a named remote in `rclone.conf`) and `concurrency` for FTP.

## Remote Paths

A remote path given to a `yd data` command is relative to the configured base: `docs/a.txt` is `<remote>:<bucket>/<prefix>/docs/a.txt`, without the prefix under `--no-prefix`, and a trailing `/` names a directory. A path beginning with the configured remote's own name and a colon (`myremote:other-bucket/a.txt`) is used as given, with neither the bucket nor the prefix, which is how to reach another bucket on the same remote:

```shell
yd data list results/                        # myremote:my-bucket/<namespace>/<tag>/results/
yd data list --no-prefix shared/             # myremote:my-bucket/shared/
yd data list myremote:other-bucket/inputs/   # as given
```

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

Select a profile with `--data-client-profile <name>` (or `--profile <name>`):

```
yd data upload --data-client-profile prod myfile.txt
yd data download --data-client-profile staging results/
```

The active profile can also be set via the `YD_DATA_CLIENT` environment variable. The `--remote`, `--bucket`, `--prefix`, and `--no-prefix` flags still apply on top of the selected profile, so individual fields can be overridden per invocation. The `YD_DATA_CLIENT_REMOTE`, `YD_DATA_CLIENT_BUCKET` and `YD_DATA_CLIENT_PREFIX` environment variables do not override a field the selected profile sets itself, only those it inherits from `[dataClient]`: a profile is chosen by name, so `yd data copy --dst-profile backup` reaches the bucket `[dataClient.backup]` names even with `YD_DATA_CLIENT_BUCKET` set for the source.

Profile names are free-form; the only reserved names are `remote`, `bucket`, and `prefix` (the scalar field names of `[dataClient]` itself). A profile takes only those three keys: any other, such as a misspelt `bukcet`, is an error, as an unknown key elsewhere in the file is, rather than being ignored while the profile uses the base section's value.

## Variable Substitutions for Data Client Properties

The `remote`, `bucket`, and `prefix` values from `[dataClient]` are available as variable substitutions in all spec files (TOML, JSON, Jsonnet) and in `userdata` scripts for every command — including `yd workrequirement submit`, `yd workerpool provision`, and `yd computerequirement instantiate`:

| Variable | Value |
|---|---|
| `{{dataClient.remote}}` | Active profile's remote (or base `[dataClient].remote`) |
| `{{dataClient.bucket}}` | Active profile's bucket |
| `{{dataClient.prefix}}` | Active profile's prefix (`{{namespace}}/{{tag}}` when none is set) |
| `{{dataClient.<name>.remote}}` | Named profile's remote, regardless of active selection |
| `{{dataClient.<name>.bucket}}` | Named profile's bucket |
| `{{dataClient.<name>.prefix}}` | Named profile's prefix (`{{namespace}}/{{tag}}` when none is set) |

For `yd data upload`/`yd data download`/`yd data delete`/`yd data list`/`yd data copy`, `{{dataClient.remote/bucket/prefix}}` reflects the fully resolved active source profile (after `--data-client-profile` selection, env vars, and CLI overrides), and under `--no-prefix` `{{dataClient.prefix}}` is empty. For all other commands, it reflects the configuration file's `[dataClient]` section (with any `--property dataClient.*` override); the `YD_DATA_CLIENT*` environment variables do not apply to it. Either way a prefix set nowhere is the default, `{{namespace}}/{{tag}}`, with or without a `[dataClient]` section, so a specification naming `{{dataClient.prefix}}` finds what `yd data upload` put under it; `prefix = ""` is no prefix.

Named profile variables are always resolved with profile fields taking precedence over the base section, so `{{dataClient.prod.prefix}}` gives the prod profile's prefix (or the base prefix if not set in `[dataClient.prod]`).

> **Note on Worker Pool / Compute Requirement specs and User Data:** In JSON/Jsonnet Worker Pool and Compute Requirement specifications, and in all User Data (whether supplied via `userData`, `userDataFile`, or `userDataFiles`), variable substitutions **must be prefixed and postfixed by double underscores** to disambiguate them from server-side Mustache processing. Use `__{{dataClient.remote}}__`, `__{{dataClient.prod.bucket}}__`, etc.

Example use in a Work Requirement spec (no underscores needed in WR JSON). The Platform requires an input's `source` to start with `rclone:` and its `destination` with `local:` (an output's the other way round; see [Specifying Data Client Inputs](work-requirements.md#specifying-data-client-inputs)); leave out the `rclone:` below if the configured `remote` already starts with it:

```json
{
  "taskDataInputs": [
    {
      "source": "rclone:{{dataClient.remote}}:{{dataClient.bucket}}/{{dataClient.prefix}}/input.csv",
      "destination": "local:input.csv"
    }
  ]
}
```

Example use in a `userdata` script (double underscores required):

```bash
#!/bin/bash
rclone copy __{{dataClient.prod.remote}}__:__{{dataClient.prod.bucket}}__/configs /tmp/configs
```

## Worked Examples

### Trying It Out on Your Own Machine

rclone's `local` backend makes a directory on your own machine the data store, so the commands can be tried with no cloud account and no credentials. In `config.toml`:

```toml
[common]
namespace = "getting-started"
tag = "first-run"

[dataClient]
remote = "store,type=local"
bucket = "/tmp/yd-store/main"

[dataClient.backup]
bucket = "/tmp/yd-store/backup"
```

The remote is an inline connection string named `store`, and the bucket an absolute directory. The prefix is the default, `{{namespace}}/{{tag}}`, so every relative path is under `/tmp/yd-store/main/getting-started/first-run`:

```shell
# Upload a directory: to store:/tmp/yd-store/main/getting-started/first-run/inputs
yd data upload --recursive inputs

# List what is under the prefix, then one directory in full
yd data list
yd data list --recursive --long inputs

# Download one file into the current directory, then every match of a wildcard into results/
yd data download inputs/b.csv
yd data download --into results 'inputs/*.txt'

# Copy the directory to the backup profile's bucket, under the same prefix
yd data copy --recursive --dst-profile backup inputs inputs
yd data list --profile backup --recursive inputs

# Reach a path outside the bucket and prefix, by the remote's own name
yd data list store:/tmp/yd-store/other

# See what a deletion would remove, then remove it (asking first)
yd data delete --dry-run --recursive inputs
yd data delete --recursive inputs
```

The recursive listing of `inputs` shows the tree:

```text
├── sub/
│   └── c.txt  6  2026-10-26T10:04:57
├── a.txt  4  2026-10-26T10:04:57
└── b.csv  8  2026-10-26T10:04:57
```

Each command first names the full remote path it works on (`Uploading 'inputs' → 'store:/tmp/yd-store/main/getting-started/first-run/inputs'`), which is the quickest way to see where a relative path lands. The same commands work unchanged against any of the stores below: only `[dataClient]` differs.

### Amazon S3

```toml
[dataClient]
remote = "S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2"
bucket = "my-bucket"
```

`env_auth=true` has rclone find the AWS credentials as the AWS tools do (the `AWS_*` environment variables, `~/.aws/credentials`, or an instance's role), so the configuration file holds none.

### An SFTP Server, Named in `rclone.conf`

A remote defined in rclone's own configuration file keeps its credentials there, and `[dataClient]` names it:

```ini
# ~/.config/rclone/rclone.conf
[files]
type = sftp
host = files.example.com
user = me
key_file = ~/.ssh/id_ed25519
connections = 8
```

```toml
[dataClient]
remote = "files"
bucket = "/data/yellowdog"
```

`bucket` is the server directory under which the prefix is added, absolute because it begins with `/`. `connections` caps how many connections rclone opens at once, which an SFTP server may limit (see the note on servers that limit connections, above).

### Several Stores, One Configuration

Each store can be a profile, and a command picks one with `--profile`, or `YD_DATA_CLIENT` for every command in a shell:

```toml
[dataClient]
prefix = "{{namespace}}/{{tag}}"

[dataClient.s3]
remote = "S3,type=s3,provider=AWS,env_auth=true,region=eu-west-2"
bucket = "my-bucket"

[dataClient.files]
remote = "files"
bucket = "/data/yellowdog"
```

```shell
yd data upload --profile s3 --recursive inputs
yd data copy --profile s3 --dst-profile files --recursive results results
```

A Work Requirement can name the same stores through the `{{dataClient.<profile>.*}}` variables (see [Variable Substitutions for Data Client Properties](#variable-substitutions-for-data-client-properties)).

## Troubleshooting

Before anything else, run `yd doctor`: its `Data client profile` rows show, for `[dataClient]` and for each profile, the remote (an inline string's credentials withheld) and the full path relative paths are taken from, without contacting anything, and its `Remote reachable` row checks that the remote can be reached at that path. Adding `--dry-run` to a command shows what it would do, and the paths it would use, without doing it.

- **`RCLONE_CONFIG names an rclone configuration file that does not exist`**, or **`No rclone configuration file found`**: a remote given by name is looked up in `rclone.conf`, which was not found. Set `RCLONE_CONFIG` to the file, create it where the message says it looked, or give the remote as an inline connection string instead.
- **`didn't find section in config file ("myremote")`**: `rclone.conf` was found but defines no remote of that name. The binary `--which-rclone` reports lists the names it does define: `<that binary> listremotes`.
- **`... does not exist`**: the path is relative to the bucket and prefix, which may not be where the file is. The full path is in the message; `yd data list` (with `--recursive`) shows what is there, `--no-prefix` leaves the prefix out, and a path beginning with the remote's name and a colon is used as given.
- **Which rclone is running**: `yd data list --which-rclone` (or any `yd data` verb) prints the binary's path and version, and `--upgrade-rclone` downloads the latest into `rclone_api`'s cache. One on your `PATH` is used in preference and never touched, so while it is there the downloaded copy, upgraded or not, is not the one that runs.
- **Transfers failing or slowing on an SFTP or FTP server**: the server may be refusing connections; cap them in the remote (see the note on servers that limit connections, above).
- **A download refused on Windows** because the remote item's name holds a character Windows does not allow in a file name: give `--destination` to name the local file.
