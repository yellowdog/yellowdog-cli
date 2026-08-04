#!/usr/bin/env bash
#
# Take an unconfigured Ubuntu (or Debian) machine to one that runs the yellowdog-cli
# test suite, including the Commander GUI tests: system packages, uv, Python, a clone
# of the repository, the package and all its extras, and then the tests.
#
# On a machine with nothing on it but curl:
#
#   curl -LsSf https://raw.githubusercontent.com/yellowdog/yellowdog-cli/next-version/setup-ubuntu.sh | bash
#
# ...which clones into ./yellowdog-cli. To pass options that way, add '-s --':
#
#   curl -LsSf <url> | bash -s -- --dir ~/src/yellowdog-cli --no-test
#
# Run from inside an existing checkout, that checkout is used as it stands and
# nothing is cloned:
#
#   ./setup-ubuntu.sh
#
# Options:
#
#   --dir PATH        where the checkout is, or should be created
#                     (default: this script's own checkout, else ./yellowdog-cli)
#   --branch NAME     branch to clone (default: next-version)
#   --repo URL        repository to clone (default: the yellowdog-cli GitHub repo)
#   --python X.Y      Python for the virtual environment (default: 3.14)
#   --no-test         install everything, but do not run the tests
#   --pyright         also run 'make pyright' at the end
#   --help
#
# Idempotent: safe to re-run. Everything it installs is either an apt package, a uv
# download under ~/.local, or inside the checkout's .venv. It never runs a git command
# that changes an existing checkout — no fetch, no branch switch, no pull.
#
# The unit tests need no YellowDog credentials and no configuration file, so nothing
# here asks for either. What this does not cover is listed when it finishes.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/yellowdog/yellowdog-cli.git}"
BRANCH="${BRANCH:-next-version}"
PYTHON_VERSION="${PYTHON_VERSION:-3.14}"
CHECKOUT=""
RUN_TESTS=1
RUN_PYRIGHT=0

usage() {
    cat <<'USAGE'
setup-ubuntu.sh — an unconfigured Ubuntu/Debian machine to one that runs the tests.

  curl -LsSf <raw url>/setup-ubuntu.sh | bash        # from nothing; clones the repo
  curl -LsSf <raw url>/setup-ubuntu.sh | bash -s -- --no-test
  ./setup-ubuntu.sh                                  # inside an existing checkout

  --dir PATH        where the checkout is, or should be created
  --branch NAME     branch to clone (default: next-version)
  --repo URL        repository to clone
  --python X.Y      Python for the virtual environment (default: 3.14)
  --no-test         install everything, but do not run the tests
  --pyright         also run 'make pyright' at the end
  --help
USAGE
}

while [ $# -gt 0 ]; do
    case "$1" in
        --no-test) RUN_TESTS=0 ;;
        --pyright) RUN_PYRIGHT=1 ;;
        --dir | --branch | --repo | --python)
            option="$1"
            shift
            [ $# -gt 0 ] || { echo "$option needs a value" >&2; exit 2; }
            case "$option" in
                --dir) CHECKOUT="$1" ;;
                --branch) BRANCH="$1" ;;
                --repo) REPO_URL="$1" ;;
                --python) PYTHON_VERSION="$1" ;;
            esac
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1 (try --help)" >&2
            exit 2
            ;;
    esac
    shift
done

log() { printf '\n\033[1m=== %s\033[0m\n' "$*"; }
die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------

if [ -r /etc/os-release ]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}:${ID_LIKE:-}" in
        *ubuntu* | *debian*) : ;;
        *) die "this script installs apt packages, so it needs Ubuntu or Debian (found '${PRETTY_NAME:-unknown}')" ;;
    esac
else
    die "cannot read /etc/os-release, so this does not look like Ubuntu or Debian"
fi

# Minimal images often have neither a non-root user nor sudo.
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
elif command -v sudo > /dev/null 2>&1; then
    SUDO="sudo"
else
    die "not running as root and 'sudo' is not installed"
fi

# Where the checkout will be. When this file was piped from curl there is no script
# directory to look at, so $0 is checked for being a real file first.
if [ -z "$CHECKOUT" ]; then
    script_path="${BASH_SOURCE[0]:-$0}"
    if [ -f "$script_path" ]; then
        script_dir="$(cd "$(dirname "$script_path")" && pwd)"
        if grep -q '^ *name = "yellowdog-cli"' "$script_dir/pyproject.toml" 2> /dev/null; then
            CHECKOUT="$script_dir"
        fi
    fi
fi
[ -n "$CHECKOUT" ] || CHECKOUT="$PWD/yellowdog-cli"

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------

log "Installing system packages"

# Every apt-get call goes through this, so that nothing can stop and ask a question.
#
# - DEBIAN_FRONTEND=noninteractive: no debconf prompts
# - NEEDRESTART_SUSPEND: Ubuntu server images install needrestart, which hooks apt and
#   puts up 'Which services should be restarted?' — a dialog that stops an unattended
#   run dead. That question is needrestart's own ('needrestart/ui-query_pkgs'), so
#   DEBIAN_FRONTEND does not cover it; its hook, /usr/lib/needrestart/apt-pinvoke,
#   checks this variable and exits before asking. Nothing is restarted as a result,
#   which is the right answer while a machine is being set up — run 'sudo needrestart'
#   afterwards if it has services worth restarting. It also suppresses the pending-
#   kernel-upgrade note.
#
# Passed through 'env' rather than exported, because sudo discards both on its way to
# apt-get: with env_reset (the default) an exported DEBIAN_FRONTEND simply does not
# arrive, which is why the dialog appeared even though this script set it. 'sudo env
# VAR=...' is not subject to sudo's environment restrictions, whereas 'sudo -E' needs
# the SETENV privilege and 'sudo VAR=... cmd' depends on the sudoers configuration.
apt_get() {
    $SUDO env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get "$@"
}

apt_get update -qq

# Install the first of these package names the archive actually has. Used where a
# library is packaged under different names across releases.
install_first_available() {
    for pkg in "$@"; do
        if apt-cache show "$pkg" > /dev/null 2>&1; then
            apt_get install -y --no-install-recommends "$pkg"
            return 0
        fi
    done
    die "none of these packages is available on this release: $*"
}

# - ca-certificates, curl: fetching uv and the Python it manages
# - git: cloning the repository
# - make: the checkout's make targets
# - build-essential: the 'jsonnet' extra has no wheel and is compiled on install
# - libatomic1: 'make pyright' runs pyright on Node, and the Node binary
#   pyright-python downloads is linked against libatomic
# - the Qt libraries: PyQt6, for the Commander GUI tests. Needed even though those
#   tests run offscreen — they are dependencies of Qt itself, not of a display, and
#   Qt still lays text out when nothing is shown
apt_get install -y --no-install-recommends \
    ca-certificates \
    curl \
    git \
    make \
    build-essential \
    libatomic1 \
    libegl1 \
    libxkbcommon0 \
    libdbus-1-3 \
    libfontconfig1

# Two more Qt dependencies whose package names move between releases. Qt links both
# directly, and nothing above depends on either, so on a bare image they are absent:
#
# - libGL: 'libgl1' from Ubuntu 20.04, the Mesa package before that
# - glib: renamed '...0t64' in Ubuntu 24.04 by the 64-bit time_t transition
#
# Without them PyQt6 raises 'libGL.so.1'/'libglib-2.0.so.0: cannot open shared object
# file', which makes every Commander test skip rather than run.
install_first_available libgl1 libgl1-mesa-glx
install_first_available libglib2.0-0t64 libglib2.0-0

# ---------------------------------------------------------------------------
# uv (which also supplies Python)
# ---------------------------------------------------------------------------

if command -v uv > /dev/null 2>&1; then
    log "uv is already installed ($(uv --version))"
else
    log "Installing uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# The installer puts uv in ~/.local/bin, which a non-login shell may not have on PATH
export PATH="$HOME/.local/bin:$PATH"
command -v uv > /dev/null 2>&1 || die "uv is still not on PATH after installing it"

# ---------------------------------------------------------------------------
# The repository
# ---------------------------------------------------------------------------

# What makes a directory usable is that it holds the source, not that it holds git
# metadata: an unpacked tarball or a copied tree is a perfectly good place to run the
# tests, and demanding '.git' turned one away.
is_source_tree() {
    grep -q '^ *name = "yellowdog-cli"' "$1/pyproject.toml" 2> /dev/null
}

if is_source_tree "$CHECKOUT"; then
    log "Using the source tree already at $CHECKOUT"
    if [ -d "$CHECKOUT/.git" ]; then
        echo "On branch '$(git -C "$CHECKOUT" branch --show-current)', and left as it is:"
        echo "this script does not fetch, switch branches or pull."
    else
        echo "Not a git checkout, which is fine — nothing here needs git metadata."
    fi
elif [ -e "$CHECKOUT" ] && [ -n "$(ls -A "$CHECKOUT" 2> /dev/null)" ]; then
    die "'$CHECKOUT' already exists, is not empty, and is not a yellowdog-cli source
tree. Move it out of the way, or point --dir somewhere else."
else
    log "Cloning $REPO_URL ($BRANCH) into $CHECKOUT"
    git clone --branch "$BRANCH" "$REPO_URL" "$CHECKOUT"
    is_source_tree "$CHECKOUT" || die "'$CHECKOUT' was cloned but holds no yellowdog-cli pyproject.toml"
fi

cd "$CHECKOUT"

# ---------------------------------------------------------------------------
# Virtual environment
# ---------------------------------------------------------------------------

log "Creating .venv on Python $PYTHON_VERSION (uv downloads it if absent)"
uv venv --python "$PYTHON_VERSION" .venv

log "Installing yellowdog-cli in editable mode with all extras"
VIRTUAL_ENV="$CHECKOUT/.venv" uv pip install -e ".[dev,jsonnet,cloudwizard,commander]"

# The yd-* commands must be on PATH: tests/test_entrypoints.py runs them as
# subprocesses, which is what activating the venv normally arranges.
export PATH="$CHECKOUT/.venv/bin:$PATH"
export VIRTUAL_ENV="$CHECKOUT/.venv"

# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

# Checked separately, and before the suite, because an unusable Qt does not fail the
# Commander tests — it skips them, and a run that quietly tests 290 fewer things than
# it should reads as a pass. Which is exactly what a missing libglib did while this
# script was being written.
log "Checking Qt can be used (the Commander tests skip when it cannot)"
if ! QT_QPA_PLATFORM=offscreen python -c '
from PyQt6.QtWidgets import QApplication, QListWidget

app = QApplication([])
listing = QListWidget()
listing.addItem("row")
listing.show()
assert listing.viewport().height() > 0, "a shown list has no visible height"
print("Qt is usable offscreen")
'; then
    die "PyQt6 cannot be used on this machine, so the Commander tests would skip rather
than run. The error above names what is missing: usually a shared library that is
packaged under a different name on this release. Install it and re-run this script."
fi

if [ "$RUN_TESTS" -eq 1 ]; then
    log "Running the test suite"
    python -m pytest -q
fi

if [ "$RUN_PYRIGHT" -eq 1 ]; then
    log "Type checking"
    make pyright
fi

log "Done"
cat <<NEXT
The checkout is at $CHECKOUT. Activate its environment with:

    source $CHECKOUT/.venv/bin/activate

Then:

    pytest -v                 # unit tests, including the Commander GUI tests
    make pyright              # type checking
    make tox                  # the unit tests on Python 3.10 - 3.14

uv is at $(command -v uv); if it was installed just now, open a new shell (or add
~/.local/bin to PATH) to pick it up outside this script.

The test categories not covered above need more than this script installs:

    --run-dryruns             # needs the python-examples-demos repo checked out
                              # alongside this one, at $(dirname "$CHECKOUT")/python-examples-demos
    --run-system              # needs real credentials (YD_KEY / YD_SECRET, or a
    --run-system-compute      # config.toml) and will provision cloud compute
    --run-demos               # as above, plus python-examples-demos

If the Commander tests ever report themselves skipped with 'Qt is unavailable', the
skip message names the library that is missing; install it and run them again.
NEXT
