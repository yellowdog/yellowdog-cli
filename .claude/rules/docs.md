---
paths:
  - "README.md"
  - "PYPI_README.md"
  - "README_CLOUDWIZARD.md"
  - "docs/**"
  - "yellowdog_cli/commander/README.md"
  - "yellowdog_cli/mcp/README.md"
---

## User Documentation

The user documentation is a guide first and a reference second. Users come to it with a task ("add Tasks to a Work Requirement I already submitted"), so every guide section answers that task before it describes the mechanism. A change to the CLI adds to the documentation without lengthening the main path: the common case stays short, and the new behaviour goes where a reader looking for it will find it.

### Guide pages and reference pages

- **Reference pages** describe everything, exhaustively, and are read by lookup: `docs/commands.md` (held to the registry by `tests/test_docs_command_list.py`), `docs/work-requirement-property-dictionary.md` (the source of the schema descriptions), `docs/json-output.md` and `docs/schemas.md`. Completeness is their job.
- **Guide pages** are everything else: `README.md`, the other `docs/*.md` pages and the extension READMEs. They are read top to bottom by someone doing something, and the rules below apply to them.

### How a guide section is written

- **Lead with the common case.** The first paragraph says what the feature is for and how to use it in the usual case, in a sentence or two, followed by a runnable example.
- **Examples are runnable and realistic.** A command line a user can paste, a `config.toml` or specification with plausible values (`namespace = "image-processing"`, `"taskType": "bash"`, `"arguments": ["process.sh", "{{task_number}}"]`), and, where it helps, what the command prints. Never placeholder values such as `in_src_path_1` or `value_1`, and never every property at once: an example shows the few properties its task needs. A section whose example depends on a configuration shows that configuration, or links to where it is shown.
- **Edge cases go in a Details subsection** (in `yellowdog_cli/commander/README.md`, a heading of its own such as `Launch Details`, since Commander's Help window and `tests/test_commander_help.py` need every heading there to be unique). Limits, timeouts, retries, interactions with other options, what happens on failure, and why the CLI behaves as it does go under a `#### Details` (or the section's next heading level) at the end of the section, or on a reference page linked from it. A sentence that needs more than one qualifier ("unless", "except when", "which", "since") probably belongs in Details.
- **One idea per sentence, one point per bullet.** A bullet that runs past two sentences is a paragraph or a subsection. A list item explaining a mechanism inside a list of options is split: the option's bullet says what it does, the mechanism goes to Details.
- **Images and Task Types are the reader's own.** YellowDog provides no stock images: an example names an image of the reader's own (an Image Family in their namespace) or a stock operating system image with the Agent installer as User Data, never a name that looks like a YellowDog-supplied image. The Agent installer defines only the `bash` Task Type, which runs `/bin/bash` with the Task's arguments; an example using any other Task Type says where it comes from (the `docker` one from `add-docker-task-type.sh`).
- **A section that lists every property is a reference**, and is titled as one ("Properties at the Task Group Level", not "Examples"). It may stay on a guide page, below the sections that show how to use them.

### When a change adds behaviour

Before adding a clause to an existing guide sentence, decide whether a reader doing the common task needs it. If not, it goes in the section's Details, creating one if needed, or on the reference page. A fix to an edge case never lengthens the main path's sentence that covers the usual case.

The repository's other documentation rules still hold: paragraphs are one line each (never hard-wrapped), every page states the current behaviour with no history (that is `CHANGELOG.md`'s), user-facing pages carry no internal language (phases, plans, branches), and the `yd` forms are named rather than the deprecated `yd-*` commands. Run the page's `make toc*` target after changing its headings.
