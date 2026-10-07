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
<!-- Added by: pwt, at: Wed Oct  7 12:13:11 BST 2026 -->

<!--te-->

## Overview

`yd-mcp` is an MCP server that exposes the YellowDog CLI's `yd-*` commands as tools for an agent.

Every tool call runs the corresponding `yd-*` command as a child process with `--json`, so behaviour, configuration precedence, output shapes and exit codes are the CLI's own by construction.

It is a stdio server, for an agent running on the same machine as the developer's own configuration — Claude Code or Claude Desktop, for instance.

## Installation

```shell
pip install -U "yellowdog-cli[mcp]"
```

`yd-mcp --help` works without the extra installed; launched without the `mcp` package present, `yd-mcp` prints an instruction to install it and exits, before serving anything.

`yd-doctor` reports the extra on its `MCP Server` row, distinguishing not installed from installed but unable to load, and `yd-version` reports the MCP SDK's version (`--mcp` for the bare number, `null` in its `--json` output when not installed).

## Launching

```shell
yd-mcp [config.toml] [-c config.toml] [-n namespace] [-t tag] [-v name=value ...]
```

A configuration file, given either as the positional argument or with `-c`/`--config` (not both), is read exactly as every other `yd-*` command reads it, and its directory becomes the working directory of every command the server runs.

Without a configuration file, every command runs with `--nc`, so only the environment (`YD_KEY`, `YD_SECRET`, `YD_NAMESPACE`, `YD_TAG`, `YD_DATA_CLIENT_*`) and the launch-time `-n`/`-t`/`-v` options are available to it.

Giving the configuration file twice, or naming one that does not exist, is refused at launch rather than at the first tool call, as is a `-v` variable whose name the CLI would refuse: one that is not `name=value`, a name breaking the CLI's rule for variable names, or one of the names the CLI sets itself (`namespace`, `tag`, `key`, `secret`, `url`), which `-n`/`-t` or the configuration set instead.

A single Ctrl-C, or a `SIGTERM`, stops the server at once, logging `stopped` to stderr. A command a tool call is still running is not waited for: Ctrl-C from a terminal interrupts it along with the server, and after a `SIGTERM` it is left running with nowhere to write its output, so it may stop part-way; a specification written for that call (see Specifications) is left behind in the working directory.

## Configuring a Client

**Claude Code:**

```shell
claude mcp add yellowdog -- yd-mcp /path/to/config.toml
```

**Claude Desktop**, in its configuration file:

```json
{
  "mcpServers": {
    "yellowdog": {
      "command": "yd-mcp",
      "args": ["/path/to/config.toml"]
    }
  }
}
```

A desktop client launches the server with a minimal `PATH`, so give the full path to `yd-mcp` if it is not found there once configured.

Every command the server runs is launched under the same Python interpreter as the server itself (`python -m yellowdog_cli.<command>`), not through the `yd-*` console scripts, because a client's `PATH` cannot be relied on to hold them.

A one-shot script that pipes requests to `yd-mcp` and then closes stdin gets no reply for a call still running when stdin closes: the SDK's stdio loop ends at end of input, so a call that outlives the script is abandoned rather than answered. A real client — Claude Code, Claude Desktop — holds stdin open for as long as the connection is alive, so this only bites a hand-rolled test harness, not normal use.

## The Tools

Kind is `read-only`, `acting` or `destructive`, carried to the client as the tool's annotations (`readOnlyHint`, `destructiveHint`); a client should ask the user before calling a destructive tool.

| Tool | Kind | Command | What it does |
|---|---|---|---|
| `yd_abort` | destructive | `yd-abort` | Abort running Tasks |
| `yd_application` | read-only | `yd-application` | Report details of the current Application |
| `yd_boost` | destructive | `yd-boost` | Boost Allowances |
| `yd_cancel` | destructive | `yd-cancel` | Cancel Work Requirements |
| `yd_cloud_info` | read-only | `yd-cloud-info` | List cloud regions, instance types and prices |
| `yd_compare` | read-only | `yd-compare` | Compare a Work Requirement or Task Group against Worker Pool(s) |
| `yd_compute_deprovision` | destructive | `yd-compute-deprovision` | Deprovision Instances, reducing their Compute Requirements' target counts |
| `yd_compute_restart` | destructive | `yd-compute-restart` | Restart Instances |
| `yd_compute_start` | destructive | `yd-compute-start` | Start stopped Compute Requirements and Instances |
| `yd_compute_stop` | destructive | `yd-compute-stop` | Stop Compute Requirements and Instances |
| `yd_copy` | acting | `yd-copy` | Copy files between remote data client locations |
| `yd_create` | acting | `yd-create` | Create and update resources |
| `yd_delete` | destructive | `yd-delete` | Delete remote data client files and directories |
| `yd_doctor` | read-only | `yd-doctor` | Check the installation, configuration and platform connection |
| `yd_download` | acting | `yd-download` | Download files from a remote data client |
| `yd_finish` | destructive | `yd-finish` | Finish Work Requirements |
| `yd_follow` | acting | `yd-follow` | Follow event streams |
| `yd_hold` | destructive | `yd-hold` | Hold (pause) running Work Requirements |
| `yd_instantiate` | acting | `yd-instantiate` | Instantiate a Compute Requirement |
| `yd_list` | read-only | `yd-list` | List YellowDog items |
| `yd_ls` | read-only | `yd-ls` | List remote data client files and directories |
| `yd_nodeaction` | destructive | `yd-nodeaction` | Submit Node Actions to Worker Pool nodes |
| `yd_priority` | destructive | `yd-priority` | Change the priority of Work Requirements and Task Groups |
| `yd_provision` | acting | `yd-provision` | Provision a Worker Pool |
| `yd_remove` | destructive | `yd-remove` | Remove resources |
| `yd_resize` | destructive | `yd-resize` | Resize Worker Pools and Compute Requirements |
| `yd_show` | read-only | `yd-show` | Show the JSON details of entities referenced by their YDIDs |
| `yd_shutdown` | destructive | `yd-shutdown` | Shut down Worker Pools and Nodes |
| `yd_start` | destructive | `yd-start` | Start held (paused) Work Requirements |
| `yd_submit` | acting | `yd-submit` | Submit a Work Requirement |
| `yd_terminate` | destructive | `yd-terminate` | Terminate Compute Requirements, Instances or Nodes |
| `yd_token` | destructive | `yd-token` | Refresh or regenerate the tokens of Configured Worker Pools |
| `yd_upload` | acting | `yd-upload` | Upload files to a remote data client |
| `yd_variables` | read-only | `yd-variables` | Report the processed values of variable substitutions |
| `yd_version` | read-only | `yd-version` | Report version information |
| `yd_wait` | acting | `yd-wait` | Wait for entities to reach a terminal state |

## Results and Errors

A successful call's `content` is one text block holding the command's `--json` document as compact JSON, and its `structuredContent` is `{"result": <document>, "exitCode": 0, "stopped": false}` — `result` is wrapped in an object because `structuredContent` must itself be an object and the document is often an array. The per-family document shapes are the CLI README's own, in [Machine-readable Output and Exit Codes](../../README.md#machine-readable-output-and-exit-codes).

`yd_show` and `yd_variables` are the two exceptions to `--json`: their commands have no such option, since they print their JSON document whatever they are given, so the server runs them with `--quiet` instead, which leaves the document alone on stdout; the warnings those two commands would print, such as an undefined variable in `yd_variables`, are suppressed by `--quiet` rather than sent to stderr.

A run that exits 1 is still a success when its document holds a record whose `outcome` or `action` is `failed` — the CLI's own per-item failure convention — since the command completed and reported what went wrong itself.

Every other non-zero exit is an error: `isError` is true, `content` carries the command's stderr (the wrapper's friendly message, `Missing configuration data`, an argparse usage error) followed by the document as compact JSON when stdout held one, and `structuredContent` adds `"exitCode"` and `"stderr"` beside `"result"` (`null` when stdout held no document at all).

Some errors carry a document that matters: `yd_wait` with a Work Requirement that failed, `yd_doctor` with a failing check, and `yd_show` with a YDID it could not show all exit 1 with their document on stdout and little or nothing on stderr, so they come back as errors with the document in both places, in the text content and as `result`. The exit code is the CLI's own, so an agent can tell a configuration error (3) from an authentication failure (4) from not found (6); see the CLI README's exit code table.

An unknown tool name or an argument that fails validation (an unknown property, the wrong type, both halves of a mutually exclusive pair) is reported the same way, as a tool error with `exitCode: 2`, never as a protocol-level error — so the agent sees the message and can correct itself.

A stopped call's result (see [Timeouts and Following](#timeouts-and-following)) includes `"stderr"` too, alongside whatever the command had already written to stdout.

## Confirmations

Destructive tools run with `--yes`, since there is no terminal for the CLI to prompt on; the `destructiveHint` annotation (true for every destructive tool) is how the client is told to ask the user before calling one.

Acting tools set `destructiveHint: false` explicitly, since the protocol's own default for a tool with no annotation is `true`.

A tool with a `dry_run` argument enumerates what it would do without doing it, exactly as the CLI's own `--dry-run` does, which an agent can call first as a lighter-weight check of what a destructive or acting call would affect.

## Specifications

The specification-taking tools — `yd_submit`, `yd_provision`, `yd_instantiate`, `yd_create` and `yd_remove` — take a `specification` (or, for `yd_create`/`yd_remove`, `specifications`) argument in place of a file option: give either a file path, exactly as the CLI takes it, or the specification itself as an inline JSON object.

An inline specification is written to a uniquely named `.yd-mcp-*.json` file in the working directory for the run, created exclusively and readable by the owner only, and removed once the run completes, whatever its outcome — so that a relative `taskDataFile` or `userDataFile` reference inside it resolves exactly as it would from a file the user had placed there themselves.

`yd_schema` gives the JSON Schema a family of specifications must follow; ask for it before composing one inline.

`yd_submit`, `yd_provision`, `yd_instantiate`, `yd_create` and `yd_nodeaction` each also take a `validate` argument, exactly as `--validate` does on the command line: it checks the specification against its schema and stops there, reporting every violation, instead of running it.

## Timeouts and Following

Every tool takes a `timeout_seconds` argument (default 300; `yd_follow`'s default is 60). Past it, the command is stopped and whatever it had already produced is returned, with `stopped: true` in the result.

`yd_follow` collects the event stream for up to `timeout_seconds` and returns the events collected as its result; it does not run to completion, since a Work Requirement, Worker Pool or Compute Requirement has no fixed lifetime to wait out.

Each command runs in a process group of its own, and stopping it at the timeout stops the whole group: a data-client command's (`yd_upload`, `yd_download`, `yd_copy`, `yd_delete`, `yd_ls`) `rclone` process stops with it, so nothing goes on transferring after the call has returned. A transfer stopped that way may leave a partly written file behind.

## What Is Not Exposed, and Why

Every tool's schema is the command's own options, less a fixed exclusion set, grouped here as the exclusion set groups them:

- **Configuration and credentials, which the server owns**: `--config`, `--key`, `--secret`, `--url`, `--docs`, `--debug`, `--pac`, `--no-format`, `--quiet`, `--env-override`, `--print-pid`, `--no-config`, `--property`.
- **Supplied by the server itself, meaningless without a terminal, or refused together with `--json`**: `--json`, `--yes`, `--interactive`, `--progress`, `--report`, `--ids-only`.
- **Machine maintenance, not platform work**: `--upgrade-rclone`, `--which-rclone`.
- **A credential in a tool result is a credential in the conversation**: `--show-keyring-passwords`, `--show-secrets`.
- **The specification file options**, replaced by each tool's own `specification`/`specifications` argument: `--work-requirement`, `--worker-pool`, `--compute-requirement`, and the equivalent positional file arguments (see [Specifications](#specifications)).

Four commands have no tool at all: `yd-cloudwizard` (interactive cloud provider setup), `yd-format-json` and `yd-jsonnet2json` (local file formatters, not platform commands), and `yd-help` (the tool list, above, is the help).

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
