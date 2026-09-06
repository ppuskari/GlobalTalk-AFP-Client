#!/bin/sh
set -eu

BRANCH=${BRANCH:-test/asp-rfork-r2-20260906}
REMOTE=${REMOTE:-origin}
REPO=${1:-.}

cd "$REPO"

git rev-parse --is-inside-work-tree >/dev/null 2>&1 || {
    echo "ERROR: not inside a Git repository: $REPO" >&2
    exit 1
}

if [ -n "$(git status --porcelain)" ]; then
    echo "ERROR: working tree has local changes; nothing was modified." >&2
    git status --short
    exit 2
fi

echo "Repository: $(git rev-parse --show-toplevel)"
echo "Remote:     $REMOTE"
echo "Branch:     $BRANCH"
echo

git config --get "remote.$REMOTE.url"
git fetch --prune "$REMOTE"

git show-ref --verify --quiet "refs/remotes/$REMOTE/$BRANCH" || {
    echo "ERROR: $REMOTE/$BRANCH does not exist." >&2
    exit 3
}

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git checkout "$BRANCH"
    git merge --ff-only "$REMOTE/$BRANCH"
else
    git checkout -b "$BRANCH" --track "$REMOTE/$BRANCH"
fi

echo
echo "PASS: local test branch is synchronized by fast-forward only."
git status --short --branch
