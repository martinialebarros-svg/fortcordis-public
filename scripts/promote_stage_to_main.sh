#!/usr/bin/env bash
set -euo pipefail

# Safe promotion script:
# - uses an isolated git worktree
# - does not touch your current working tree/runtime files
# - pushes stage -> main
#
# Usage:
#   bash scripts/promote_stage_to_main.sh
#   bash scripts/promote_stage_to_main.sh stage main
#
# Optional:
#   PREFER_STAGE_ON_CONFLICTS=0 bash scripts/promote_stage_to_main.sh

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_BRANCH="${1:-stage}"
DST_BRANCH="${2:-main}"
PREFER_STAGE_ON_CONFLICTS="${PREFER_STAGE_ON_CONFLICTS:-1}"

WORKTREE_DIR="${ROOT_DIR}-promote-${SRC_BRANCH}-to-${DST_BRANCH}-$(date +%Y%m%d%H%M%S)"

cleanup() {
  local exit_code=$?
  if [[ $exit_code -eq 0 ]]; then
    git -C "$ROOT_DIR" worktree remove "$WORKTREE_DIR" --force >/dev/null 2>&1 || true
  else
    echo "[ERROR] Promotion failed. Temporary worktree kept for inspection:"
    echo "        $WORKTREE_DIR"
  fi
}
trap cleanup EXIT

echo "[INFO] Repo: $ROOT_DIR"
cd "$ROOT_DIR"

git fetch origin

if ! git rev-parse --verify --quiet "origin/${SRC_BRANCH}" >/dev/null; then
  echo "[ERROR] Remote branch origin/${SRC_BRANCH} not found."
  exit 1
fi

if ! git rev-parse --verify --quiet "origin/${DST_BRANCH}" >/dev/null; then
  echo "[ERROR] Remote branch origin/${DST_BRANCH} not found."
  exit 1
fi

echo "[INFO] Creating isolated worktree: $WORKTREE_DIR"
git worktree add "$WORKTREE_DIR" "origin/${DST_BRANCH}" >/dev/null

cd "$WORKTREE_DIR"
git fetch origin

MERGE_MSG="chore(release): promote ${SRC_BRANCH} -> ${DST_BRANCH}"
if [[ "$PREFER_STAGE_ON_CONFLICTS" == "1" ]]; then
  echo "[INFO] Merge strategy: prefer ${SRC_BRANCH} on conflicts (-X theirs)."
  git merge --no-ff -X theirs "origin/${SRC_BRANCH}" -m "$MERGE_MSG"
else
  echo "[INFO] Merge strategy: manual conflict resolution."
  git merge --no-ff "origin/${SRC_BRANCH}" -m "$MERGE_MSG"
fi

NEW_HASH="$(git rev-parse --short HEAD)"
echo "[INFO] Pushing ${DST_BRANCH} (HEAD=${NEW_HASH})"
git push origin "HEAD:${DST_BRANCH}"

echo "[OK] Promotion complete: ${SRC_BRANCH} -> ${DST_BRANCH} (${NEW_HASH})"
