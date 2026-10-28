# Installation

<!--ts-->
   * [Installing uv](#installing-uv)
   * [Option 1: uv tool](#option-1-uv-tool)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli)
      * [Update](#update)
      * [With Jsonnet support](#with-jsonnet-support)
   * [Option 2: a virtual environment created with uv](#option-2-a-virtual-environment-created-with-uv)
      * [Create and activate a virtual environment](#create-and-activate-a-virtual-environment)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli-1)
      * [Update](#update-1)
      * [With Jsonnet support](#with-jsonnet-support-1)
   * [Option 3: pip in a virtual environment](#option-3-pip-in-a-virtual-environment)
      * [Create and activate a virtual environment](#create-and-activate-a-virtual-environment-1)
      * [Install the YellowDog CLI](#install-the-yellowdog-cli-2)
      * [Update](#update-2)
      * [With Jsonnet support](#with-jsonnet-support-2)

<!-- Created by https://github.com/ekalinin/github-markdown-toc -->
<!-- Added by: pwt, at: Tue Oct 27 16:19:00 GMT 2026 -->

<!--te-->

Python 3.10 or later is required. There are several ways to install the CLI, each keeping it and its dependencies in an environment of their own; choose the one that fits how you work:

- **[uv tool](#option-1-uv-tool)** — the commands on your PATH everywhere, with no environment to activate. uv supplies Python itself if you have none.
- **[A virtual environment created with uv](#option-2-a-virtual-environment-created-with-uv)** — an environment you activate, for using the CLI alongside other Python tools. uv supplies Python itself if you have none.
- **[pip in a virtual environment](#option-3-pip-in-a-virtual-environment)** — the standard Python tooling, with a Python you have installed.

Other installers, such as pipx, work too.

## Installing uv

**[uv](https://docs.astral.sh/uv/)** installs Python packages, and Python itself: the first two options need it, and no Python of your own. See the [uv installation docs](https://docs.astral.sh/uv/getting-started/installation/) for full instructions. Quick options:

| Platform         | Command                                            |
|------------------|----------------------------------------------------|
| macOS / Linux    | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| macOS (Homebrew) | `brew install uv`                                  |
| Windows          | `winget install --id=astral-sh.uv -e`              |

## Option 1: uv tool

uv installs the CLI into an environment of its own and puts the `yd` command on your PATH, downloading a suitable Python if none is installed.

### Install the YellowDog CLI

```shell
uv tool install yellowdog-cli
```

To choose the Python it runs on, which uv downloads if it is not installed:

```shell
uv tool install --python 3.14 yellowdog-cli
```

### Update

```shell
uv tool upgrade yellowdog-cli
```

### With Jsonnet support

```shell
uv tool install "yellowdog-cli[jsonnet]"
```

## Option 2: a virtual environment created with uv

uv creates the virtual environment, downloading the Python you ask for if it is not installed, and installs the CLI into it.

### Create and activate a virtual environment

```shell
uv venv --python 3.14 yd-env
source yd-env/bin/activate   # macOS / Linux
yd-env\Scripts\activate      # Windows
```

### Install the YellowDog CLI

```shell
uv pip install yellowdog-cli
```

### Update

```shell
uv pip install -U yellowdog-cli
```

### With Jsonnet support

```shell
uv pip install -U "yellowdog-cli[jsonnet]"
```

> **Note:** You will need to activate the virtual environment (`source yd-env/bin/activate`) each time you open a new terminal session, or add the activation to your shell profile.

## Option 3: pip in a virtual environment

This uses the standard Python tooling, with a Python you have installed. If you don't have Python 3.10 or later, download it from **[python.org](https://www.python.org/downloads/)**, or use your system package manager:

| Platform        | Command                             |
|-----------------|-------------------------------------|
| macOS           | `brew install python`               |
| Ubuntu / Debian | `sudo apt install python3`          |
| Windows         | `winget install Python.Python.3.12` |

### Create and activate a virtual environment

```shell
python3 -m venv yd-env
source yd-env/bin/activate   # macOS / Linux
yd-env\Scripts\activate      # Windows
```

### Install the YellowDog CLI

```shell
pip install -U yellowdog-cli
```

### Update

```shell
pip install -U yellowdog-cli
```

### With Jsonnet support

```shell
pip install -U "yellowdog-cli[jsonnet]"
```

> **Note:** As with uv's, you will need to activate the virtual environment each time you open a new terminal session, or add the activation to your shell profile.
