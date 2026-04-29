#!/usr/bin/env bash
# release.sh — Automate the yellowdog-cli release process.
#
# Usage:
#   ./release.sh            # dry run — print every step without executing (default)
#   ./release.sh --release  # execute the release for real
#
# Must be run from the root of the repository on the 'next-version' branch
# with a clean working tree.

set -euo pipefail

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DRY_RUN=true
if [[ "${1-}" == "--release" ]]; then
    DRY_RUN=false
else
    echo "*** DRY RUN — no commands will be executed (pass --release to release for real) ***"
    echo
fi

_run() {
    echo "+ $*"
    if ! $DRY_RUN; then
        "$@"
    fi
}

_confirm() {
    local prompt="$1"
    if $DRY_RUN; then
        echo "[dry-run] Would prompt: $prompt → assuming yes"
        return 0
    fi
    read -r -p "$prompt [y/N] " answer
    case "$answer" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) echo "Aborted."; exit 1 ;;
    esac
}

_die() {
    echo "ERROR: $*" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

# Must be inside a git repo
git rev-parse --git-dir > /dev/null 2>&1 || _die "Not inside a git repository."

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT_BRANCH" != "next-version" ]]; then
    _die "Must be on the 'next-version' branch (currently on '$CURRENT_BRANCH')."
fi

# Working tree must be clean
if ! git diff --quiet || ! git diff --cached --quiet; then
    if $DRY_RUN; then
        echo "[dry-run] WARNING: Working tree is not clean (ignored in dry-run)"
    else
        _die "Working tree is not clean. Commit or stash your changes first."
    fi
fi

# Pull latest
echo "Pulling latest 'next-version' from origin..."
_run git pull origin next-version

# ---------------------------------------------------------------------------
# Determine new version
# ---------------------------------------------------------------------------

VERSION_FILE="yellowdog_cli/_version.py"
CURRENT_VERSION=$(grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' "$VERSION_FILE" | head -1)
echo
echo "Current version: $CURRENT_VERSION"

if $DRY_RUN; then
    NEW_VERSION="X.Y.Z"
else
    read -r -p "New version (e.g. $CURRENT_VERSION): " NEW_VERSION
    if [[ -z "$NEW_VERSION" ]]; then
        _die "No version supplied."
    fi
    if ! [[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        _die "Version must be in MAJOR.MINOR.PATCH format, got: $NEW_VERSION"
    fi
    if [[ "$NEW_VERSION" == "$CURRENT_VERSION" ]]; then
        _die "New version ($NEW_VERSION) is the same as the current version."
    fi
fi

echo
echo "Releasing version $NEW_VERSION"
echo

# ---------------------------------------------------------------------------
# Bump version in _version.py
# ---------------------------------------------------------------------------

echo "--- Bumping version ---"
if ! $DRY_RUN; then
    sed -i.bak "s/__version__ = \"$CURRENT_VERSION\"/__version__ = \"$NEW_VERSION\"/" "$VERSION_FILE"
    rm -f "${VERSION_FILE}.bak"
    grep "__version__" "$VERSION_FILE"
fi

# ---------------------------------------------------------------------------
# Format, check, test
# ---------------------------------------------------------------------------

echo
echo "--- Formatting ---"
_run make format

echo
echo "--- Build and distribution check ---"
_run make pypi_check

echo
echo "--- Running tests ---"
_run pytest -v

# ---------------------------------------------------------------------------
# Commit version bump
# ---------------------------------------------------------------------------

echo
echo "--- Committing version bump ---"
_run git add "$VERSION_FILE"
_run git commit -m "Bump version to v$NEW_VERSION"

# ---------------------------------------------------------------------------
# Merge to main and tag
# ---------------------------------------------------------------------------

echo
echo "--- Merging to main ---"
_run git checkout main
_run git pull origin main
_run git merge --no-ff next-version -m "Release v$NEW_VERSION"
_run git tag -a "v$NEW_VERSION" -m "Version $NEW_VERSION"

# ---------------------------------------------------------------------------
# Push main + tags (with confirmation)
# ---------------------------------------------------------------------------

echo
echo "About to push 'main' and tag 'v$NEW_VERSION' to origin."
_confirm "Push now?"
_run git push origin main --tags

# ---------------------------------------------------------------------------
# Upload to PyPI (with confirmation)
# ---------------------------------------------------------------------------

echo
echo "About to upload to PyPI."
_confirm "Upload to PyPI now?"
_run make pypi_upload

# ---------------------------------------------------------------------------
# Return to next-version and push
# ---------------------------------------------------------------------------

echo
echo "--- Returning to next-version ---"
_run git checkout next-version
_run git push origin next-version

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------

echo
echo "=== Release v$NEW_VERSION complete ==="
