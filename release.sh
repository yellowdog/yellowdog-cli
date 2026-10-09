#!/usr/bin/env bash
# release.sh — Automate the yellowdog-cli release process.
#
# Usage:
#   ./release.sh            # dry run — print every step without executing (default)
#   ./release.sh --release  # execute the release for real
#
# Must be run from the root of the repository on the 'next-version' branch
# with a clean working tree, and with this release's notes under
# '## Unreleased' in CHANGELOG.md, which the version bump stamps with the
# version and date; they are the release tag's message, and are printed at
# the end for the release ticket. It asks whether to run the tests, and
# refuses to release unsigned commits, which 'main' requires to be signed.

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

# A yes/no question whose answer is the return status, yes by default; unlike
# _confirm, 'no' carries on
_ask() {
    local prompt="$1"
    if $DRY_RUN; then
        echo "[dry-run] Would ask: $prompt → assuming yes"
        return 0
    fi
    read -r -p "$prompt [Y/n] " answer
    case "$answer" in
        [nN][oO]|[nN]) return 1 ;;
        *) return 0 ;;
    esac
}

_die() {
    echo "ERROR: $*" >&2
    exit 1
}

CHANGELOG="CHANGELOG.md"

# The body of one '## <heading>' section of the changelog: the lines after it,
# up to the next '## ' heading ('### ' subsections included)
_changelog_section() {
    awk -v heading="$1" '
        /^## / { if (found) exit; if ($0 == "## " heading) { found = 1; next } }
        found
    ' "$CHANGELOG"
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

# Every commit being released must be signed: 'main' requires it, and an
# account allowed to bypass that is only warned, once the push has happened
# (the pre-push hook, scripts/pre-push, refuses too, but only after the
# merge and the tag below)
echo
echo "Checking that every commit to be released is signed..."
_run git fetch origin main
if ! unsigned=$(scripts/unsigned_commits.sh origin/main..HEAD); then
    echo "$unsigned"
    if $DRY_RUN; then
        echo "[dry-run] WARNING: Unsigned commits (ignored in dry-run)"
    else
        _die "Unsigned commits would go to 'main': re-sign them first (see scripts/unsigned_commits.sh)."
    fi
fi

# The release notes: written as the changes landed, under '## Unreleased'
[[ -f "$CHANGELOG" ]] || _die "No $CHANGELOG."
if [[ -z "$(_changelog_section Unreleased | tr -d '[:space:]')" ]]; then
    if $DRY_RUN; then
        echo "[dry-run] WARNING: Nothing under '## Unreleased' in $CHANGELOG (ignored in dry-run)"
    else
        _die "Nothing under '## Unreleased' in $CHANGELOG: add this release's notes first."
    fi
fi
echo
echo "--- Release notes (## Unreleased in $CHANGELOG) ---"
_changelog_section Unreleased

# The tests below run in this venv alone, with every extra installed, which
# can hide a failure: 'make tox' runs them on every supported Python version,
# with only the dev, commander and mcp extras
echo
echo "REMINDER: run 'make tox' on this commit before releasing. The tests this"
echo "script runs use this venv only, which can hide failures on other Python"
echo "versions or without the optional extras."
_confirm "Has 'make tox' passed on this commit?"

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

# The notes under '## Unreleased' become this version's, and a fresh,
# empty '## Unreleased' takes their place
RELEASE_HEADING="$NEW_VERSION — $(date +%Y-%m-%d)"
echo
echo "--- Stamping $CHANGELOG: '## $RELEASE_HEADING' ---"
if ! $DRY_RUN; then
    awk -v heading="## $RELEASE_HEADING" '
        !done && $0 == "## Unreleased" { print; print ""; print heading; done = 1; next }
        { print }
    ' "$CHANGELOG" > "$CHANGELOG.new"
    mv "$CHANGELOG.new" "$CHANGELOG"
fi

# This version's notes, for the tag's message and the release ticket
NOTES_FILE=$(mktemp)
trap 'rm -f "$NOTES_FILE"' EXIT
{
    echo "Version $NEW_VERSION"
    echo
    if $DRY_RUN; then
        _changelog_section Unreleased
    else
        _changelog_section "$RELEASE_HEADING"
    fi
} > "$NOTES_FILE"

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
if _ask "Run the tests (pytest -v -n 8)?"; then
    echo "--- Running tests ---"
    _run pytest -v -n 8
else
    echo "--- Skipping the tests ---"
fi

# ---------------------------------------------------------------------------
# Commit version bump
# ---------------------------------------------------------------------------

echo
echo "--- Committing version bump ---"
_run git add "$VERSION_FILE" "$CHANGELOG"
_run git commit -m "Bump version to v$NEW_VERSION"

# ---------------------------------------------------------------------------
# Merge to main and tag
# ---------------------------------------------------------------------------

echo
echo "--- Merging to main ---"
_run git checkout main
_run git pull origin main
_run git merge --no-ff next-version -m "Release v$NEW_VERSION"
_run git tag -a "v$NEW_VERSION" -F "$NOTES_FILE"

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
echo
echo "--- Release notes, for the release ticket ---"
cat "$NOTES_FILE"
