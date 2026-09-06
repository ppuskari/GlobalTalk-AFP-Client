#!/bin/sh
set -eu

BRANCH=${BRANCH:-integration/rfork-r3-20260906}
REMOTE=${REMOTE:-origin}
REPO=${1:-$HOME/build/GlobalTalk-AFP-Client}

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

git config --get "remote.$REMOTE.url" >/dev/null || {
    echo "ERROR: remote '$REMOTE' does not exist." >&2
    exit 3
}

git fetch --prune "$REMOTE"

git show-ref --verify --quiet "refs/remotes/$REMOTE/$BRANCH" || {
    echo "ERROR: $REMOTE/$BRANCH does not exist." >&2
    exit 4
}

if git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git checkout "$BRANCH"
    if ! git merge --ff-only "$REMOTE/$BRANCH"; then
        echo
        echo "Fast-forward was not possible. No reset was performed." >&2
        git status --short --branch
        git log --oneline --decorate --graph --max-count=16 \
            "$BRANCH" "$REMOTE/$BRANCH"
        exit 5
    fi
else
    git checkout -b "$BRANCH" --track "$REMOTE/$BRANCH"
fi

echo
echo "PASS: Linux integration branch synchronized by fast-forward only."
git status --short --branch
