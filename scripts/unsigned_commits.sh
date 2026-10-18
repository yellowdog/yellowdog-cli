#!/usr/bin/env bash
# unsigned_commits.sh — List the commits in a range that 'main' would refuse.
#
# Usage:
#   scripts/unsigned_commits.sh <rev-list arguments...>
#   e.g. scripts/unsigned_commits.sh origin/main..next-version
#
# GitHub's ruleset on 'main' requires verified signatures. Prints one line per
# commit that is unsigned (%G? 'N') or whose signature is bad ('B'), and exits
# 1 if there are any. A signature that is good but cannot be checked here
# (missing key, untrusted, expired) is let through: GitHub checks it against
# the key it holds. Rewriting history with 'git filter-branch' or
# 'git filter-repo' drops signatures; 'git rebase' re-signs under
# commit.gpgsign.

set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 <rev-list arguments...>" >&2
    exit 2
fi

found=0
while read -r sha status subject; do
    case "$status" in
        N) echo "  ${sha:0:8} unsigned:      $subject"; found=1 ;;
        B) echo "  ${sha:0:8} bad signature: $subject"; found=1 ;;
    esac
done < <(git log --format='%H %G? %s' "$@")

exit "$found"
