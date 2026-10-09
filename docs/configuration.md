# Configuration

<!--ts-->
   * [Naming Rules](#naming-rules)
   * [Common Properties](#common-properties)
      * [Importing common Properties](#importing-common-properties)
      * [HTTPS Proxy Support](#https-proxy-support)
      * [Specifying Common Properties using the Command Line or Environment Variables](#specifying-common-properties-using-the-command-line-or-environment-variables)
      * [Overriding Arbitrary TOML Properties on the Command Line](#overriding-arbitrary-toml-properties-on-the-command-line)
      * [Support for .env Files](#support-for-env-files)
      * [Variable Substitutions in Common Properties](#variable-substitutions-in-common-properties)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Fri Oct  9 10:46:46 BST 2026 -->

<!--te-->


By default, the operation of all commands is configured using a **TOML** configuration file. TOML v1.1.0 is supported, allowing multi-line tables, etc.

The configuration file has four possible sections:

1. A `common` section that contains required security properties for interacting with the YellowDog platform, sets the Namespace in which YellowDog assets and objects are created, and a Tag that is used for tagging and naming assets and objects.
2. A `workRequirement` section that defines the properties of Work Requirements to be submitted to the YellowDog platform.
3. A `workerPool` section that defines the properties of Provisioned Worker Pools to be created using the YellowDog platform. (This can be substituted by a `computeRequirement` section if instance provisioning is all that's required.)
4. A `dataClient` section that configures the remote data store used by the `yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, and `yd-copy` commands.

There is a documented template TOML file provided in [config-template.toml](../config-template.toml), containing the main properties that can be configured.

The name of the configuration file can be supplied in two different ways:

1. On the command line, using the `--config` or `-c` options, e.g.:<br>`yd-submit -c jobs/config_1.toml`
2. If not supplied, the commands look for a `config.toml` file in the current directory

Run `yd-doctor` to see which configuration file was found and where each value came from.

Every command checks the configuration file against its schema as it starts, and warns of each problem it finds without stopping: a value of the wrong type (e.g., `maxNodes = "ten"`), a property in a section that does not read it (e.g., `minNodes` under `[workRequirement]`), or an unknown property given with `--property`. Each warning names the file and the property, e.g., `'config.toml': workerPool.maxNodes: must be an integer`. A property that no section reads, or one that is no longer supported, is an error. The data client commands (`yd-upload`, `yd-download`, `yd-delete`, `yd-ls`, `yd-copy`) check only the `[common]` and `[dataClient]` sections, the only ones they read. A `{{variable}}` substitution is accepted wherever a value is expected, a value such as `idleNodeTimeout = "5"` that the CLI converts to a number is accepted as it stands, and `yd-schema config` prints the schema itself. `yd-doctor` reports the same problems in its `Config schema` row.

## Naming Rules

All entity names used within the YellowDog Platform must comply with the following rules:

- Names can only contain the following: lowercase letters, digits, hyphens and underscores (note that spaces are not permitted)
- Names must start with a letter
- Names must end with a letter or digit
- Name length must be 60 characters or fewer

These restrictions apply to entities including Namespaces, Tags, Work Requirements, Task Groups, Tasks, Worker Pools, and Compute Requirements, and also apply to entities that are currently used indirectly by these scripts, including Usernames, Credentials, Keyrings, Compute Sources and Compute Templates.

Work Requirement, Task Group and Task names supplied to `yd-submit` are automatically adjusted to comply with these rules: characters are switched to lower case, spaces and full stops become underscores, forward slashes become hyphens, any remaining invalid characters are discarded, and the result is truncated to 60 characters. If the adjusted name doesn't start with a letter it is prefixed with `yd_` — e.g. `2024-run` becomes `yd_2024-run` — and a warning is printed naming both the supplied name and the one that will be used in its place. A name left with no usable characters at all is an error rather than something to correct, as is a name that isn't a string: `name = 123` is reported as a configuration error.

When a Work Requirement, Worker Pool or Compute Requirement name is not supplied, one is generated automatically in the form `<tag>_YYMMDD-HHMMSSd-pp`, e.g. `my-tag_260921-1309153-4f`, where `d` is tenths of a second and `pp` is the process ID in two base 36 digits. The last two characters are deliberately separated by a hyphen because they are not part of the timestamp: they are what stops commands launched simultaneously, from `yd-commander` or from a shell loop, generating the same name. The generated suffix occupies 18 characters, so the tag must be 42 characters or fewer.

[Variable Substitutions](variables.md) and [Specifying Work Requirements using CSV Data](work-requirements.md#specifying-work-requirements-using-csv-data) describe variable substitutions implemented with user-defined and CSV-file-defined variables. As a type modifier within these substitution expressions, the `format_name:` option is available, and works in the same manner as `num:`, `bool:`, etc. The `format_name:` modifier will convert the substituted string into one that satisfies YellowDog naming, by switching characters to lower case, etc.

For example, a variable substitution `{{format_name:ligand_name}}`, with variable `ligand_name` set to `DCCCDE_00000s`, would substitute to become `dcccde_00000s`, and would be acceptable for use as a component of a YellowDog name. Because such a substitution is usually only one component of a name, `format_name:` does not apply the `yd_` prefix and issues no warning: a value that starts with a digit is left as it is.

## Common Properties

The `[common]` section of the configuration file can contain the following properties:

| Property    | Description                                                                                 |
|:------------|:--------------------------------------------------------------------------------------------|
| `key`       | The **key ID** of the YellowDog Application under which the commands will run               |
| `secret`    | The **key secret** of the YellowDog Application under which the commands will run           |
| `namespace` | The **namespace** to be used for grouping resources. Defaults to `default`                  |
| `tag`       | The **tag** to be used for tagging resources and naming objects. Defaults to `{{username}}` |
| `url`       | The **URL** of the YellowDog Platform API endpoint. Defaults to `https://api.yellowdog.ai`. |
| `usePAC`    | Use PAC (proxy autoconfiguration) if set to `true`                                          |
| `variables` | A table containing **variable substitutions** (see [Variable Substitutions](variables.md)) |
| `certificates` | The path of a **CA certificates bundle** to use for HTTPS requests (sets the `REQUESTS_CA_BUNDLE` environment variable) |

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

Properties set in the imported file are superseded by any of the same properties that are present in the main configuration file.

### HTTPS Proxy Support

The commands will respect the value of the environment variable `HTTPS_PROXY` if routing through a proxy is required.

In addition, commands can use proxy autoconfiguration (PAC) if the `--pac` command-line option is specified, or if the `usePAC` property is set to `true` in the `[common]` section of the `config.toml` file.

The proxy that a command ends up using is reported only under `--debug`, whether it came from `HTTPS_PROXY` or from PAC; PAC finding no proxy is reported there too.

### Specifying Common Properties using the Command Line or Environment Variables

All the common properties can be set using command-line options, or in environment variables.

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

When setting the value of the above properties, a property set on the command line takes precedence over one set via an environment variable, and both take precedence over a value set in the configuration file.

**Exception**: if the configuration file is explicitly selected using the `--config`/`-c` option, its contents take precedence over environment variables (but not over properties set on the command line). This makes it easy to direct a command at a specific configuration without first having to unset environment variables.

If all the required common properties are set using the command line or environment variables, then the entire `common` section of the TOML file can be omitted.

### Overriding Arbitrary TOML Properties on the Command Line

Any property in the TOML configuration file can be overridden on the command line using the `--property` flag (repeatable):

```
--property 'section.key=value'
```

The `section` must be one of `common`, `dataClient`, `workRequirement`, `workerPool`, or `computeRequirement`. The `value` is interpreted as JSON first (so booleans, numbers, lists, and dicts are handled correctly), falling back to a plain string if JSON parsing fails.

Properties that take a string value are the exception: their values are always used as supplied, so `--property 'workRequirement.name=123'` sets the name `123` rather than the number 123. Supplying `null` still unsets a property, whatever its type.

Examples:

```bash
# Override a single string value
yd-submit --property 'common.namespace=myproject'

# Override a numeric value
yd-provision --property 'workerPool.targetInstanceCount=4'

# Override a list
yd-submit --property 'workRequirement.workerTags=["gpu","large"]'

# Override a boolean
yd-provision --property 'workerPool.maintainInstanceCount=true'

# Override a string property: the value is used as supplied
yd-submit --property 'workRequirement.tag=2024'

# Multiple overrides
yd-submit --property 'workRequirement.taskCount=3' \
          --property 'workRequirement.priority=1.5'
```

`--property` overrides are applied after the TOML file is loaded, so they take effect regardless of what the file contains. Specific CLI flags (`--namespace`, `--tag`, etc.) are applied on top of them. `{{variable}}` substitutions within values are resolved in the normal way.

Use `--dry-run` to verify the effect of an override before submitting:

```bash
yd-submit --property 'workRequirement.priority=2.0' --dry-run --quiet
```

### Support for `.env` Files

Environment variables can also be set in a `.env` file.

The `.env` file is located by checking the following locations in order:

1. The directory containing the active `config.toml` file (as specified by `--config`, or the default `config.toml` in the current directory). This allows a `.env` file to live alongside its `config.toml` and be found even when commands are run from a different directory.
2. Searching upward from the current working directory (standard `python-dotenv` behaviour).

Entries in the `.env` file will not overwrite existing environment variables — i.e. environment variables take precedence over entries in the `.env` file. This precedence can be reversed by using the `--env-override` command-line option, or by setting the `YD_ENV_OVERRIDE` environment variable (e.g. in `.bashrc`/`.zshrc`) to make `.env` values always take precedence.

With `--debug`, environment variables sourced from a `.env` file whose names start with `YD` are reported as the command starts. Variables whose names do not start with `YD` are never reported, but they are still applied.

### Variable Substitutions in Common Properties

Note the use of `{{username}}` in the value of the `tag` property example above: this is a **variable substitution** that can optionally be used to insert the login username of the user running the commands. So, for username `abc`, the `tag` would be set to `testing-abc`. This can be helpful to disambiguate multiple users running with the same configuration data.

Variable substitutions are described in detail in [Variable Substitutions](variables.md).
