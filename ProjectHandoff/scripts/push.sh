#!/usr/bin/env bash
# ProjectHandoff — stage, commit and push ONLY ProjectHandoff paths.
#
# Usage:
#   scripts/push.sh "commit message"
#
# Notes:
# - Never touches the untracked scratch files at the repository root.
# - Refuses to run if there is nothing staged to commit.
# - Never force-pushes; verifies the remote ref after pushing.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" # repo root = parent of ProjectHandoff
PROJECT_DIR="ProjectHandoff"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 \"commit message\"" >&2
  exit 2
fi

MESSAGE="$1"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# Stage only ProjectHandoff paths (respects ProjectHandoff/.gitignore).
git add -- "${PROJECT_DIR}"

if git diff --cached --quiet; then
  echo "nothing staged to commit under ${PROJECT_DIR}/ — aborting."
  exit 1
fi

git commit -m "${MESSAGE}"

# Push and verify the remote ref matches the pushed commit.
if git remote get-url origin >/dev/null 2>&1; then
  git push origin "${BRANCH}"
  LOCAL_SHA="$(git rev-parse HEAD)"
  REMOTE_SHA="$(git rev-parse "origin/${BRANCH}")"
  if [[ "${LOCAL_SHA}" == "${REMOTE_SHA}" ]]; then
    echo "push verified: origin/${BRANCH} @ ${LOCAL_SHA}"
  else
    echo "ERROR: remote ref origin/${BRANCH} (${REMOTE_SHA}) != local HEAD (${LOCAL_SHA})" >&2
    exit 1
  fi
else
  echo "no 'origin' remote configured — commit created locally only."
fi
