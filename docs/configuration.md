# Configuration

<!--ts-->
   * [Choosing the Configuration File](#choosing-the-configuration-file)
      * [Details](#details)
   * [Checking the Configuration File](#checking-the-configuration-file)
      * [Details](#details-1)
   * [Naming Rules](#naming-rules)
      * [Details](#details-2)
   * [Common Properties](#common-properties)
      * [Importing common Properties](#importing-common-properties)
      * [HTTPS Proxy Support](#https-proxy-support)
      * [Specifying Common Properties using the Command Line or Environment Variables](#specifying-common-properties-using-the-command-line-or-environment-variables)
         * [Details](#details-3)
      * [Overriding Arbitrary TOML Properties on the Command Line](#overriding-arbitrary-toml-properties-on-the-command-line)
         * [Details](#details-4)
      * [Support for .env Files](#support-for-env-files)
         * [Details](#details-5)
      * [Variable Substitutions in Common Properties](#variable-substitutions-in-common-properties)
   * [Which Value Wins](#which-value-wins)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:12:21 GMT 2026 -->

<!--te-->


Every command reads its settings from a **TOML** configuration file, `config.toml` in the current directory. To start one, run `yd init`, which asks for the `[common]` properties and writes a `config.toml` (or, with `--user`, your own file; see [yd init](commands.md#yd-init)). A minimal file holds the Application's key and secret, and the namespace and tag to work in:

```toml
[common]
    key = "asdfghjklzxcvb-1234567"
    secret = "qwertyuiopasdfghjklzxcvbnm1234567890qwertyu"
    namespace = "image-processing"
    tag = "render"
```

The configuration file has four possible sections:

1. A `common` section that contains required security properties for interacting with the YellowDog platform, sets the Namespace in which YellowDog assets and objects are created, and a Tag that is used for tagging and naming assets and objects.
2. A `workRequirement` section that defines the properties of Work Requirements to be submitted to the YellowDog platform.
3. A `workerPool` section that defines the properties of Provisioned Worker Pools to be created using the YellowDog platform. A `computeRequirement` section can be used in its place if instance provisioning is all that's required. Both may be present, and are merged; a property set in both is an error.
4. A `dataClient` section that configures the remote data store used by the `yd data upload`, `yd data download`, `yd data delete`, `yd data list`, and `yd data copy` commands.

Each section's properties are described with what they configure: [Work Requirements](work-requirements.md), [Worker Pools](worker-pools.md) and the [data client](data-client.md). The documented template [config-template.toml](../config-template.toml) contains the main properties that can be configured. TOML v1.1.0 is supported, allowing multi-line tables, etc.

## Choosing the Configuration File

The configuration file is chosen in this order:

1. The file named with the `--config` or `-c` option, e.g.:<br>`yd workrequirement submit -c jobs/render.toml`
2. If none is named, `config.toml` in the current directory
3. If there is none, your own configuration file, `~/.config/yellowdog/config.toml`, so that one set of credentials and defaults serves every directory without a `config.toml` of its own

Run `yd doctor` to see which configuration file was found and where each value came from.

`--no-config` (or `--nc`) reads no configuration file at all, even one named with `--config`. The command takes its configuration from the command line and the environment alone.

### Details

**Where your own file is.** Your own file is `$XDG_CONFIG_HOME/yellowdog/config.toml` where `XDG_CONFIG_HOME` is set, on every platform.

**How your own file is read.** Your own file is read exactly as a `config.toml` in the current directory would be. Environment variables take precedence over it, and paths in it are relative to its directory. The exception is `certificates`, which is relative to the current directory, as in any configuration file.

**One file only.** A `config.toml` in the current directory, or one named with `--config`, is read in place of your own file, never as well.

**`--no-config` and variables.** With `--no-config`, `{{config_dir_abs}}` and `{{config_dir_name}}` are not defined.

## Checking the Configuration File

Every command checks the configuration file as it starts. A property name the CLI does not know stops the command with an error (exit code 3), as does a retired one, whose error names the property that replaces it.

Every other problem is a warning, found by checking the file against its schema, and the command carries on. For example, with `minNodes` set under `[workRequirement]`, which does not read it:

```
WARNING : 'config.toml': workRequirement: 'minNodes' is not read in this section (see yd schema config)
```

The warnings report a value of the wrong type (e.g., `maxNodes = "ten"`), a property in a section that does not read it, and an unknown property given with `--property`. Each names the file and the property. `yd schema config` prints the schema itself, and `yd doctor` reports the same problems in its `Config schema` row.

### Details

**`--quiet`.** `--quiet` suppresses warnings, so the schema check, which only warns, is not made. The errors are still reported: an unknown or retired property name in the file, or a property a `[dataClient.<profile>]` section does not take, stops the command under `--quiet` too. An unknown property given with `--property` is only a warning, so under `--quiet` nothing reports it. `yd doctor` still reports the schema's warnings in its `Config schema` row, as `WARN` lines that `yd doctor --quiet` keeps.

**The data client commands.** `yd data upload`, `yd data download`, `yd data delete`, `yd data list` and `yd data copy` check only the `[common]` and `[dataClient]` sections, the only ones they read.

**Values the check accepts.** A `{{variable}}` substitution is accepted wherever a value is expected. A value that the CLI converts to a number, such as `idleNodeTimeout = "5"`, is accepted as it stands.

## Naming Rules

All entity names used within the YellowDog Platform must comply with the following rules:

- Names can only contain the following: lowercase letters, digits, hyphens and underscores (note that spaces are not permitted)
- Names must start with a letter
- Names must end with a letter or digit
- Name length must be 60 characters or fewer

These restrictions apply to entities including Namespaces, Tags, Work Requirements, Task Groups, Tasks, Worker Pools, and Compute Requirements, and also apply to entities that are currently used indirectly by these commands, including Usernames, Credentials, Keyrings, Compute Sources and Compute Templates.

Work Requirement, Task Group and Task names supplied to `yd workrequirement submit` are adjusted to comply with these rules:

- characters are switched to lower case
- spaces and full stops become underscores
- forward slashes become hyphens
- any remaining invalid characters are discarded
- a name that doesn't start with a letter is prefixed with `yd_`
- the result is truncated to 60 characters

So `Trailer Render v2.1` becomes `trailer_render_v2_1`, `Q3/Results (final)` becomes `q3-results_final`, and `2024 Run` becomes `yd_2024_run`.

When a Work Requirement, Worker Pool or Compute Requirement name is not supplied, one is generated automatically in the form `<tag>_YYMMDD-HHMMSSd-pp`, e.g. `render_260921-1309153-4f`, where `d` is tenths of a second and `pp` is the process ID in two base 36 digits.

[Variable Substitutions](variables.md) and [Specifying Work Requirements using CSV Data](work-requirements.md#specifying-work-requirements-using-csv-data) describe variable substitutions implemented with user-defined and CSV-file-defined variables. Within these, the `format_name:` type modifier, used like `num:`, `bool:` and the others, converts the substituted string into one that satisfies YellowDog naming. For example, `{{format_name:ligand_name}}`, with the variable `ligand_name` set to `DCCCDE_00000s`, substitutes `dcccde_00000s`, which is acceptable as a component of a YellowDog name.

### Details

**Names ending `-` or `_`.** The adjustment does not correct a name that ends with `-` or `_`: it is passed on as it is.

**Warnings.** Discarding characters and truncating are each warned of the first time they change a name in a run, since Task names, formatted one per Task, would otherwise give a warning each. The `yd_` prefix is warned of each time, naming both the supplied name and the one used in its place. The other adjustments are not warned of.

**Names that cannot be adjusted.** A name left with no usable characters at all is an error rather than something to correct. So is a name that isn't a string: `name = 123` is reported as a configuration error.

**Task Group names.** Task Group names must be unique once adjusted: with `taskGroupCount`, include `{{task_group_number}}` in the name.

**The generated suffix.** The last two characters of a generated name are separated by a hyphen because they are not part of the timestamp. They are what stops commands launched simultaneously, from `yd commander` or from a shell loop, generating the same name. The generated suffix occupies 18 characters, so the tag must be 42 characters or fewer.

**`format_name:` adds no prefix.** Because such a substitution is usually only one component of a name, `format_name:` does not apply the `yd_` prefix and issues no warning: a value that starts with a digit is left as it is.

## Common Properties

The `[common]` section of the configuration file can contain the following properties:

| Property    | Description                                                                                 |
|:------------|:--------------------------------------------------------------------------------------------|
| `key`       | The **key ID** of the YellowDog Application under which the commands will run               |
| `secret`    | The **key secret** of the YellowDog Application under which the commands will run           |
| `namespace` | The **namespace** to be used for grouping resources. Defaults to `default`                  |
| `tag`       | The **tag** to be used for tagging resources and naming objects. Defaults to `{{username}}` |
| `url`       | The **URL** of the YellowDog Platform API endpoint, beginning `https://` (or `http://`). Defaults to `https://api.yellowdog.ai`. |
| `usePAC`    | Use PAC (proxy autoconfiguration) if set to `true`                                          |
| `readTimeout` | How many **seconds** to wait for a response from the Platform before a request fails. Defaults to `90`; `0` waits indefinitely. A Task batch whose response times out is resubmitted only when all its Tasks have names |
| `variables` | A table containing **variable substitutions** (see [Variable Substitutions](variables.md)) |
| `certificates` | The path of a **CA certificates bundle** to use for HTTPS requests (sets the `REQUESTS_CA_BUNDLE` environment variable); a relative path is relative to the current directory, not the configuration file's |

An example `common` section is shown below:

```toml
[common]
    key = "asdfghjklzxcvb-1234567"
    secret = "qwertyuiopasdfghjklzxcvbnm1234567890qwertyu"
    namespace = "project-x"
    tag = "testing-{{username}}"
```

Indentation is optional in TOML files and is for readability only.

### Importing `common` Properties

The `common` section can import properties from a separate TOML file, using the `importCommon` property. For example, the `key` and `secret` might be in a shared TOML file called `app_credentials.toml`, with the following contents:

```toml
[common]
    key = "asdfghjklzxcvb-1234567"
    secret = "qwertyuiopasdfghjklzxcvbnm1234567890qwertyu"
```

This could be imported into the main configuration as follows:

```toml
[common]
    importCommon = "app_credentials.toml"

    namespace = "project-x"
    tag = "testing-{{username}}"
```

The imported file's path is relative to the main configuration file's directory, and may contain `{{variable}}` substitutions. Only its `[common]` section is read, and an `importCommon` within it is ignored: imports do not chain.

Properties set in the imported file are superseded by any of the same properties that are present in the main configuration file, and so are its `[common.variables]`: a variable both files define takes the main file's value, whether or not the main file was chosen with `--config`.

### HTTPS Proxy Support

The commands will respect the value of the environment variable `HTTPS_PROXY` if routing through a proxy is required.

In addition, commands can use proxy autoconfiguration (PAC) if the `--pac` command-line option is specified, or if the `usePAC` property is set to `true` in the `[common]` section of the `config.toml` file.

The proxy that a command ends up using is reported only under `--debug`, whether it came from `HTTPS_PROXY` or from PAC; PAC finding no proxy is reported there too.

### Specifying Common Properties using the Command Line or Environment Variables

The common properties can also be set with command-line options or environment variables, for example to work in another namespace for one command:

```bash
yd workerpool provision --namespace image-processing-test
YD_NAMESPACE=image-processing-test yd workerpool provision
```

The **command-line options** are as follows:

- `--key` or `-k`
- `--secret` or `-s`
- `--namespace` or `-n`
- `--tag` or `-t`
- `--url` or `-u`
- `--pac`

These options can also be listed by running a command with the `--help` or `-h` option.

The **environment variables** are as follows:

- `YD_KEY` (or `YD_API_KEY_ID`)
- `YD_SECRET` (or `YD_API_KEY_SECRET`)
- `YD_URL` (or `YD_API_URL`)
- `YD_NAMESPACE`
- `YD_TAG`
- `YD_READ_TIMEOUT` (`readTimeout`)

A property set on the command line takes precedence over one set in an environment variable, and both take precedence over the configuration file; [Which Value Wins](#which-value-wins) gives the whole order.

**Exception**: if the configuration file is explicitly selected using the `--config`/`-c` option, its contents take precedence over environment variables (but not over properties set on the command line). This makes it easy to direct a command at a specific configuration without first having to unset environment variables.

If all the required common properties are set using the command line or environment variables, then the entire `common` section of the TOML file can be omitted.

#### Details

**Properties without an option or a variable.** `usePAC` has an option (`--pac`) but no environment variable. `readTimeout` has an environment variable but no option; `--property common.readTimeout=<seconds>` sets it on the command line. `certificates`, `importCommon` and `variables` have neither.

### Overriding Arbitrary TOML Properties on the Command Line

Any property in the TOML configuration file can be overridden on the command line using the `--property` option, `--property 'section.key=value'`, repeated for each property:

```bash
yd workerpool provision --property 'workerPool.maxNodes=8' --property 'workerPool.workerTag=render-gpu'
```

The `section` is one of `common`, `dataClient`, `workRequirement`, `workerPool`, or `computeRequirement`. The `value` is interpreted as JSON first, so booleans, numbers, lists, and dicts are handled correctly, and is otherwise a plain string. Properties that take a string value are the exception: their values are always used as supplied, so `--property 'workRequirement.name=123'` sets the name `123` rather than the number 123. Supplying `null` unsets a property, whatever its type.

More examples:

```bash
# Override a single string value
yd workrequirement submit --property 'common.namespace=image-processing-test'

# Override a numeric value
yd workerpool provision --property 'workerPool.targetInstanceCount=4'

# Override a list
yd workrequirement submit --property 'workRequirement.workerTags=["gpu","large"]'

# Override a boolean
yd workerpool provision --property 'workerPool.maintainInstanceCount=true'

# Override a string property: the value is used as supplied
yd workrequirement submit --property 'workRequirement.tag=2024'

# Multiple overrides
yd workrequirement submit --property 'workRequirement.taskCount=3' \
          --property 'workRequirement.priority=1.5'
```

Use `--dry-run` to verify the effect of an override before submitting:

```bash
yd workrequirement submit --property 'workRequirement.priority=2.0' --dry-run --quiet
```

#### Details

**After the file.** `--property` overrides are applied after the TOML file is loaded, so they take effect regardless of what the file contains.

**Specification files.** An override in `workRequirement`, `workerPool` or `computeRequirement` also replaces a specification file's own value for the property, wherever the specification sets it, and each replacement is reported as the command starts. So `--property workRequirement.priority=5` is the priority however the specification sets it. A longer path, such as `workRequirement.retryPolicy.maxRetries`, replaces only that part of the property.

**Precedence.** Overrides are command-line values, so they take precedence over environment variables: `--property common.namespace=image-processing-test` is used whatever `YD_NAMESPACE` holds, and `--property dataClient.bucket=render-assets` whatever `YD_DATA_CLIENT_BUCKET` holds. Specific options (`--namespace`, `--tag`, etc.) are applied on top of them.

**`null`.** An override to `null` removes the file's value without supplying one, so an environment variable then applies.

**Variables.** `{{variable}}` substitutions within values are resolved in the normal way.

### Support for `.env` Files

Environment variables can also be set in a `.env` file, for example to keep the Application's key and secret out of `config.toml`:

```bash
YD_KEY=asdfghjklzxcvb-1234567
YD_SECRET=qwertyuiopasdfghjklzxcvbnm1234567890qwertyu
```

The `.env` file is located by checking the following locations in order:

1. The directory containing the active `config.toml` file (as specified by `--config`, or the default `config.toml` in the current directory). This allows a `.env` file to live alongside its `config.toml` and be found even when commands are run from a different directory.
2. Searching upward from the current working directory (standard `python-dotenv` behaviour).

Entries in the `.env` file do not overwrite existing environment variables. To make `.env` values take precedence, use the `--env-override` option, or set the `YD_ENV_OVERRIDE` environment variable (e.g. in `.bashrc`/`.zshrc`) to do so always.

#### Details

**Your own configuration file.** When your own configuration file is the one read, the search upward from the current directory comes first, and a `.env` file beside your own file is used only when that finds none.

**`YD_ENV_OVERRIDE` values.** Any value turns it on except `0`, `false`, `no` and `off`, in any case, which leave it off.

**`--debug`.** With `--debug`, environment variables sourced from a `.env` file whose names start with `YD` are reported as the command starts. Variables whose names do not start with `YD` are never reported, but they are still applied.

### Variable Substitutions in Common Properties

Note the use of `{{username}}` in the value of the `tag` property example above: this is a **variable substitution** that can optionally be used to insert the login username of the user running the commands. So, for username `abc`, the `tag` would be set to `testing-abc`. This can be helpful to disambiguate multiple users running with the same configuration data.

Variable substitutions are described in detail in [Variable Substitutions](variables.md).

## Which Value Wins

A setting can come from several places at once. The table gives each source's rank, 1 winning, for the four kinds of setting: a `[common]` property (`key`, `secret`, `namespace`, `tag`, `url`, `readTimeout`), a [variable](variables.md), a `[dataClient]` field (`remote`, `bucket`, `prefix`) as the `yd data` commands read it, and a property of the other sections (`[workRequirement]`, `[workerPool]`, `[computeRequirement]`). A dash means the source does not set that kind.

| Source | `[common]` | Variables | `[dataClient]` | Other sections |
|:---|:---:|:---:|:---:|:---:|
| The setting's own command-line option: `--namespace`/`-n`, `--tag`/`-t`, `--key`, `--secret`, `--url`; `--remote`, `--bucket`, `--prefix`; `--task-count`, `--target` and the like | 1 | — | 1 | 1 |
| `--variable`/`-v`, or `--property common.variables.<name>=<value>` | — | 1 | — | — |
| `--property <section>.<key>=<value>` | 2 | — | 2 | 2 |
| A specification file's own value (a Work Requirement, Worker Pool or Compute Requirement) | — | — | — | 3 |
| The configuration file chosen with `--config`/`-c`, and the file it imports with `importCommon` | 3 | 2 | 3 | 4 |
| A field the selected data client profile sets itself | — | — | 3 | — |
| The environment: `YD_KEY`, `YD_NAMESPACE` and the others, `YD_VAR_*`, `YD_DATA_CLIENT_*` | 4 | 3 | 4 | — |
| A `.env` file (ranked above the environment with `--env-override` or `YD_ENV_OVERRIDE`) | 5 | 4 | 5 | — |
| The configuration file found without `--config` (`./config.toml`, or your own), and the file it imports | 6 | 5 | 6 | 4 |
| The CLI's default | 7 | 6 | 7 | 5 |

Within a configuration file, its own values win over those of the file it imports with `importCommon`, whether or not it was chosen with `--config`. The configuration file is read with `--config`'s rank or without it, never both: the rows for it are one file, ranked differently by how it was chosen. So with `--config`, an environment variable that sets the same thing to something else is passed over: `yd doctor` lists each one so passed over, as a `WARN`, and `--debug` says so as it happens, naming the variable and the setting, never the value.

Some notes on the columns:

- **`[common]`**: the reserved `{{namespace}}`, `{{tag}}`, `{{key}}`, `{{secret}}` and `{{url}}` variables always hold the values this column chooses. `--no-config` (`--nc`) leaves out every configuration file row.
- **Variables**: the default variables (`{{username}}`, `{{date}}`, `{{random}}` and the others) are the last row. A `{{env:NAME}}` substitution reads the environment variable directly and takes no part in the order.
- **`[dataClient]`**: the profile itself is chosen by `--data-client-profile`/`--profile`, else `YD_DATA_CLIENT`. For the commands other than `yd data`, the `{{dataClient.*}}` variables come from the configuration file alone (with any `--property` override), not from the environment or the `yd data` options.
- **Other sections**: these have no environment variables. A `--property` override wins over a specification file's own value wherever the specification sets the property: at the Work Requirement, Task Group and Task levels alike, and in a Worker Pool or Compute Requirement specification. Where the specification does not set it, the configuration's value, the override included, fills it in, as ever. `name` and `tag`, which are each level's own, are replaced at the Work Requirement level only. Most command-line options win over the specification too, as each option's description says; `--task-type` is the exception, setting the configuration's `taskType`, which a specification's own `taskType` replaces.
