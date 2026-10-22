# YellowDog MCP Server

<!--ts-->
   * [Overview](#overview)
   * [Installation](#installation)
   * [Launching](#launching)
   * [Configuring a Client](#configuring-a-client)
   * [The Tools](#the-tools)
   * [Results and Errors](#results-and-errors)
   * [Confirmations](#confirmations)
   * [Specifications](#specifications)
   * [Timeouts and Following](#timeouts-and-following)
   * [What Is Not Exposed, and Why](#what-is-not-exposed-and-why)
   * [Namespace, Tag and Variables](#namespace-tag-and-variables)
   * [Logging](#logging)
   * [Security Notes](#security-notes)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Mon Oct 12 11:18:31 BST 2026 -->

<!--te-->

## Overview

`yd mcp` is an MCP server that exposes the YellowDog CLI's `yd` commands as tools for an agent.

Every tool call runs the corresponding `yd` command as a child process with `--json`, so behaviour, configuration precedence, output shapes and exit codes are the CLI's own by construction.

It is a stdio server, for an agent running on the same machine as the developer's own configuration — Claude Code or Claude Desktop, for instance.

## Installation

```shell
pip install -U "yellowdog-cli[mcp]"
```

`yd mcp --help` works without the extra installed; launched without the `mcp` package present, `yd mcp` prints an instruction to install it and exits, before serving anything.

`yd doctor` reports the extra on its `MCP Server` row, distinguishing not installed from installed but unable to load, and `yd version` reports the MCP SDK's version (`--mcp` for the bare number, `null` in its `--json` output when not installed).

## Launching

```shell
yd mcp [config.toml] [-c config.toml] [-n namespace] [-t tag] [-v name=value ...]
```

A configuration file, given either as the positional argument or with `-c`/`--config` (not both), is read exactly as every other `yd` command reads it, and its directory becomes the working directory of every command the server runs.

Without a configuration file, every command runs with `--nc`, so only the environment (`YD_KEY`, `YD_SECRET`, `YD_NAMESPACE`, `YD_TAG`, `YD_DATA_CLIENT_*`) and the launch-time `-n`/`-t`/`-v` options are available to it.

Giving the configuration file twice, or naming one that does not exist, is refused at launch rather than at the first tool call, as is a `-v` variable whose name the CLI would refuse: one that is not `name=value`, a name breaking the CLI's rule for variable names, or one of the names the CLI sets itself (`namespace`, `tag`, `key`, `secret`, `url`), which `-n`/`-t` or the configuration set instead.

A single Ctrl-C, or a `SIGTERM`, stops the server at once, logging `stopped` to stderr. A command a tool call is still running is not waited for: Ctrl-C from a terminal interrupts it along with the server, and after a `SIGTERM` it is left running with nowhere to write its output, so it may stop part-way; a specification written for that call (see Specifications) is left behind in the working directory.

## Configuring a Client

**Claude Code:**

```shell
claude mcp add yellowdog -- yd mcp /path/to/config.toml
```

**Claude Desktop**, in its configuration file:

```json
{
  "mcpServers": {
    "yellowdog": {
      "command": "yd",
      "args": ["mcp", "/path/to/config.toml"]
    }
  }
}
```

A desktop client launches the server with a minimal `PATH`, so give the full path to `yd` if it is not found there once configured.

A client configured with `yd-mcp`, the command's deprecated name, also works; the server then warns on stderr that the name is deprecated.

Every command the server runs is launched under the same Python interpreter as the server itself (`python -m yellowdog_cli.yd <command>`, or `python -m yellowdog_cli.yd <noun> <verb>`), not through the `yd` command on the `PATH`, because a client's `PATH` cannot be relied on to hold it.

A one-shot script that pipes requests to `yd mcp` and then closes stdin gets no reply for a call still running when stdin closes: the SDK's stdio loop ends at end of input, so a call that outlives the script is abandoned rather than answered. A real client — Claude Code, Claude Desktop — holds stdin open for as long as the connection is alive, so this only bites a hand-rolled test harness, not normal use.

## The Tools

Kind is `read-only`, `acting` or `destructive`, carried to the client as the tool's annotations (`readOnlyHint`, `destructiveHint`); a client should ask the user before calling a destructive tool.

| Tool | Kind | Command | What it does |
|---|---|---|---|
| `yd_allowance_boost` | destructive | `yd allowance boost` | Boost Allowances |
| `yd_application` | read-only | `yd application` | Report details of the current Application |
| `yd_cloudinfo_instance_types` | read-only | `yd cloudinfo instance-types` | List instance types |
| `yd_cloudinfo_prices` | read-only | `yd cloudinfo prices` | List instance prices |
| `yd_cloudinfo_regions` | read-only | `yd cloudinfo regions` | List cloud regions |
| `yd_cloudinfo_sub_regions` | read-only | `yd cloudinfo sub-regions` | List cloud sub-regions |
| `yd_computerequirement_autoshutdown` | destructive | `yd computerequirement autoshutdown` | Set when Compute Requirements are automatically terminated |
| `yd_computerequirement_instantiate` | acting | `yd computerequirement instantiate` | Instantiate a Compute Requirement |
| `yd_computerequirement_reprovision` | destructive | `yd computerequirement reprovision` | Reprovision Compute Requirements, restoring their target instance counts |
| `yd_computerequirement_resize` | destructive | `yd computerequirement resize` | Resize a Compute Requirement |
| `yd_computerequirement_start` | destructive | `yd computerequirement start` | Start stopped Compute Requirements |
| `yd_computerequirement_stop` | destructive | `yd computerequirement stop` | Stop Compute Requirements |
| `yd_computerequirement_terminate` | destructive | `yd computerequirement terminate` | Terminate Compute Requirements |
| `yd_data_copy` | acting | `yd data copy` | Copy files between remote data client locations |
| `yd_data_delete` | destructive | `yd data delete` | Delete remote data client files and directories |
| `yd_data_download` | acting | `yd data download` | Download files from a remote data client |
| `yd_data_ls` | read-only | `yd data ls` | List remote data client files and directories |
| `yd_data_upload` | acting | `yd data upload` | Upload files to a remote data client |
| `yd_doctor` | read-only | `yd doctor` | Check the installation, configuration and platform connection |
| `yd_follow` | acting | `yd follow` | Follow event streams |
| `yd_instance_deprovision` | destructive | `yd instance deprovision` | Deprovision Instances, reducing their Compute Requirements' target counts |
| `yd_instance_restart` | destructive | `yd instance restart` | Restart Instances |
| `yd_instance_start` | destructive | `yd instance start` | Start stopped Instances |
| `yd_instance_stop` | destructive | `yd instance stop` | Stop Instances |
| `yd_instance_terminate` | destructive | `yd instance terminate` | Terminate Instances |
| `yd_list` | read-only | `yd list` | List YellowDog items |
| `yd_node_action` | destructive | `yd node action` | Submit Node Actions to Worker Pool nodes |
| `yd_node_deprovision` | destructive | `yd node deprovision` | Deprovision the Instances of Nodes, reducing their Compute Requirements' target counts |
| `yd_node_restart` | destructive | `yd node restart` | Restart the Instances of Nodes |
| `yd_node_shutdown` | destructive | `yd node shutdown` | Shut down Nodes |
| `yd_node_start` | destructive | `yd node start` | Start the stopped Instances of Nodes |
| `yd_node_stop` | destructive | `yd node stop` | Stop the Instances of Nodes |
| `yd_node_terminate` | destructive | `yd node terminate` | Terminate the Instances of Nodes |
| `yd_resource_create` | acting | `yd resource create` | Create and update resources |
| `yd_resource_remove` | destructive | `yd resource remove` | Remove resources |
| `yd_schema` | read-only | `yd schema` | Print, write or check the specification schemas |
| `yd_show` | read-only | `yd show` | Show the JSON details of entities referenced by their YDIDs |
| `yd_task_abort` | destructive | `yd task abort` | Abort running Tasks |
| `yd_taskgroup_compare` | read-only | `yd taskgroup compare` | Compare a Task Group against Worker Pool(s) |
| `yd_taskgroup_priority` | destructive | `yd taskgroup priority` | Change the priority of Task Groups and Work Requirements |
| `yd_variables` | read-only | `yd variables` | Report the processed values of variable substitutions |
| `yd_version` | read-only | `yd version` | Report version information |
| `yd_wait` | acting | `yd wait` | Wait for entities to reach a terminal state |
| `yd_workerpool_provision` | acting | `yd workerpool provision` | Provision a Worker Pool |
| `yd_workerpool_resize` | destructive | `yd workerpool resize` | Resize a Worker Pool |
| `yd_workerpool_shutdown` | destructive | `yd workerpool shutdown` | Shut down Worker Pools |
| `yd_workerpool_token` | destructive | `yd workerpool token` | Refresh or regenerate the tokens of Configured Worker Pools |
| `yd_workrequirement_cancel` | destructive | `yd workrequirement cancel` | Cancel Work Requirements |
| `yd_workrequirement_compare` | read-only | `yd workrequirement compare` | Compare a Work Requirement against Worker Pool(s) |
| `yd_workrequirement_finish` | destructive | `yd workrequirement finish` | Finish Work Requirements |
| `yd_workrequirement_hold` | destructive | `yd workrequirement hold` | Hold (pause) running Work Requirements |
| `yd_workrequirement_priority` | destructive | `yd workrequirement priority` | Change the priority of Work Requirements and Task Groups |
| `yd_workrequirement_start` | destructive | `yd workrequirement start` | Start held (paused) Work Requirements |
| `yd_workrequirement_submit` | acting | `yd workrequirement submit` | Submit a Work Requirement |

A tool is named for the command it runs, `yd_workrequirement_submit` for `yd workrequirement submit`, and offers that verb's options alone: `yd_instance_terminate` takes Instances and has no `namespace`. The nouns' `list`, `show`, `follow` and `wait` verbs have no tools of their own, since `yd_list`, `yd_show`, `yd_follow` and `yd_wait` take any type.

## Results and Errors

A successful call's `content` is one text block holding the command's `--json` document as compact JSON, and its `structuredContent` is `{"result": <document>, "exitCode": 0, "stopped": false}` — `result` is wrapped in an object because `structuredContent` must itself be an object and the document is often an array. The per-family document shapes are the CLI README's own, in [Machine-readable Output and Exit Codes](../../docs/json-output.md).

`yd_show` and `yd_variables` are the two exceptions to `--json`: their commands have no such option, since they print their JSON document whatever they are given, so the server runs them with `--quiet` instead, which leaves the document alone on stdout; the warnings those two commands would print, such as an undefined variable in `yd_variables`, are suppressed by `--quiet` rather than sent to stderr.

A run that exits non-zero is still a success when its document holds a record whose `outcome` or `action` is `failed` — the CLI's own per-item failure convention — since the command completed and reported what went wrong itself; its exit code is then the cause the failures share (6 when every target was not found, 5 when each was refused) or 1. An authentication (4) or connection (8) failure, which stops the command part-way, is an error whatever it recorded.

Every other non-zero exit is an error: `isError` is true, `content` carries the command's stderr (the wrapper's friendly message, `Missing configuration data`, an argparse usage error) followed by the document as compact JSON when stdout held one, and `structuredContent` adds `"exitCode"` and `"stderr"` beside `"result"` (`null` when stdout held no document at all).

Some errors carry a document that matters: `yd_wait` with a Work Requirement that failed, `yd_doctor` with a failing check, and `yd_show` with a YDID it could not show all exit 1 with their document on stdout and little or nothing on stderr, so they come back as errors with the document in both places, in the text content and as `result`. The exit code is the CLI's own, so an agent can tell a configuration error (3) from an authentication failure (4) from not found (6); see the CLI README's exit code table.

An unknown tool name or an argument that fails validation (an unknown property, the wrong type, both halves of a mutually exclusive pair) is reported the same way, as a tool error with `exitCode: 2`, never as a protocol-level error — so the agent sees the message and can correct itself.

A stopped call's result (see [Timeouts and Following](#timeouts-and-following)) includes `"stderr"` too, alongside whatever the command had already written to stdout.

## Confirmations

Destructive tools run with `--yes`, since there is no terminal for the CLI to prompt on; the `destructiveHint` annotation (true for every destructive tool) is how the client is told to ask the user before calling one.

Acting tools set `destructiveHint: false` explicitly, since the protocol's own default for a tool with no annotation is `true`.

The CLI's action commands act on everything matching the namespace and tag when given no targets, and `yd data delete --recursive` on the whole default prefix. Since the server passes `--yes`, a tool call leaving its targets out would do that without anyone having asked for it, so the tools for those commands (`yd_task_abort`, `yd_workrequirement_cancel`, `yd_computerequirement_autoshutdown`, `yd_computerequirement_reprovision`, `yd_computerequirement_start`, `yd_computerequirement_stop`, `yd_computerequirement_terminate`, `yd_data_delete`, `yd_workrequirement_finish`, `yd_workrequirement_hold`, `yd_workrequirement_start` and `yd_workerpool_shutdown`) refuse a call with no targets unless it sets `all_in_scope` to `true`, and refuse one that sets both. The tools that take Instance or Node IDs alone (`yd_instance_terminate`, `yd_node_shutdown` and the rest) need at least one.

A tool with a `dry_run` argument enumerates what it would do without doing it, exactly as the CLI's own `--dry-run` does, which an agent can call first as a lighter-weight check of what a destructive or acting call would affect.

## Specifications

The specification-taking tools — `yd_workrequirement_submit`, `yd_workerpool_provision`, `yd_computerequirement_instantiate`, `yd_resource_create` and `yd_resource_remove` — take a `specification` (or, for `yd_resource_create`/`yd_resource_remove`, `specifications`) argument in place of a file option: give either a file path, exactly as the CLI takes it, or the specification itself as an inline JSON object.

An inline specification is written to a uniquely named `.yd-mcp-*.json` file in the working directory for the run, created exclusively and readable by the owner only, and removed once the run completes, whatever its outcome — so that a relative `taskDataFile` or `userDataFile` reference inside it resolves exactly as it would from a file the user had placed there themselves.

`yd_schema` gives the JSON Schema a family of specifications must follow; ask for it before composing one inline.

`yd_workrequirement_submit`, `yd_workerpool_provision`, `yd_computerequirement_instantiate`, `yd_resource_create` and `yd_node_action` each also take a `validate` argument, exactly as `--validate` does on the command line: it checks the specification against its schema and stops there, reporting every violation, instead of running it.

## Timeouts and Following

Every tool takes a `timeout_seconds` argument (default 300; `yd_follow`'s default is 60). Past it, the command is stopped and whatever it had already produced is returned, with `stopped: true` in the result. The command is interrupted first, as a Ctrl-C would, and given a few seconds to write its `--json` document of what it had done (the Tasks a `yd_workrequirement_submit` created, the files a `yd_data_download` fetched) before it is killed; on Windows it is killed at once, and the result holds only what it had written. A command's own wait (`yd_wait`'s `timeout`, `yd_workerpool_resize`'s `wait`) has no limit by default, so set `timeout_seconds` above it when the command should be let finish.

`yd_follow` collects the event stream for up to `timeout_seconds` and returns the events collected as its result; it does not run to completion, since a Work Requirement, Worker Pool or Compute Requirement has no fixed lifetime to wait out.

Each command runs in a process group of its own, and stopping it at the timeout stops the whole group: a data-client command's (`yd_data_upload`, `yd_data_download`, `yd_data_copy`, `yd_data_delete`, `yd_data_ls`) `rclone` process stops with it, so nothing goes on transferring after the call has returned. A transfer stopped that way may leave a partly written file behind.

## What Is Not Exposed, and Why

Every tool's schema is the command's own options, less a fixed exclusion set, grouped here as the exclusion set groups them:

- **Configuration and credentials, which the server owns**: `--config`, `--key`, `--secret`, `--url`, `--docs`, `--debug`, `--pac`, `--no-format`, `--quiet`, `--env-override`, `--print-pid`, `--no-config`, `--property`.
- **Supplied by the server itself, meaningless without a terminal, or refused together with `--json`**: `--json`, `--yes`, `--interactive`, `--progress`, `--report`, `--ids-only`.
- **Machine maintenance, not platform work**: `--upgrade-rclone`, `--which-rclone`.
- **A credential in a tool result is a credential in the conversation**: `--show-keyring-passwords`, `--show-secrets`.
- **The specification file options**, replaced by each tool's own `specification`/`specifications` argument: `yd workrequirement submit`'s `--work-requirement`, `yd workerpool provision`'s and `yd computerequirement instantiate`'s `--worker-pool`, `yd computerequirement instantiate`'s `--compute-requirement`, and the equivalent positional file arguments (see [Specifications](#specifications)). `yd_node_action`'s `worker_pool`, which shares the name but is no file, is offered as on the command line.

Four commands have no tool at all: `yd cloudwizard` (interactive cloud provider setup), `yd format-json` and `yd jsonnet2json` (local file formatters, not platform commands), and `yd help` (the tool list, above, is the help). Nor do the deprecated commands the nouns replace (`yd-submit`, `yd-terminate` and the rest): their noun verbs' tools stand in for them.

## Namespace, Tag and Variables

The `-n`/`-t`/`-v` values given at launch apply to every command the server runs. A tool's own `namespace`, `tag` or `variable` argument, where the underlying command has one, is added to the command line after the launch-time values, and so overrides them for that call.

## Logging

Nothing is written to stdout, which is the MCP transport; the server logs to stderr instead, through Python's `logging` module at `INFO`.

It logs its own start, and, for each tool call, the full command line it runs and the child's exit code — which is what a client's server log shows.

Because that command line includes the variables, both the launch-time `-v` values and a tool call's own `variable` argument, a variable holding a secret is logged in full there; keep secrets in the configuration file or the environment instead, neither of which is logged this way.

## Security Notes

Credentials reach a command only from the configuration file, or the environment, that the server itself was launched with; no tool can name a different configuration file, application key or secret, since `--config`, `--key`, `--secret` and `--url` are excluded from every tool (see [What Is Not Exposed, and Why](#what-is-not-exposed-and-why)).

An inline specification is written to disk in the working directory for the duration of a call (see [Specifications](#specifications)), as a uniquely named `.yd-mcp-*.json` file created exclusively — so a symlink placed there in advance is never followed — and readable by the owner only; anything sensitive belongs in a variable substitution or a referenced file instead of inline in the specification itself.

A specification given as a path is read by the command exactly as the CLI reads one, so it can be any file the server's own process can read, and a `dry_run` call returns the processed specification as its result: a tool call can therefore read any such file, as JSON, TOML or Jsonnet, back into the conversation.

Every option value a tool passes on is joined to its flag as one argument (`--namespace=<value>`), so a value that looks like an option, such as `--show-secrets`, is only ever read as the value.

`--show-secrets` and `--show-keyring-passwords` are excluded from every tool that has them, so a credential already held in the configuration cannot be asked back out through a tool result. `yd_variables` redacts the application key and secret, variables whose names look like credentials, and the parameters of inline rclone connection strings whether or not the call names them, so naming `secret` reports `<REDACTED>` rather than the value.
