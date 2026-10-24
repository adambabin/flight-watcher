#!/usr/bin/env bash
# Keep the tracker's memory on a separate `state` branch so main stays code-only.
#   state.sh pull   clone the state branch into .state (or start an empty one)
#   state.sh push   commit .state and push it back
set -euo pipefail

REMOTE="${STATE_REMOTE:-https://x-access-token:${GH_TOKEN:-}@github.com/${GITHUB_REPOSITORY:-}.git}"
DIR=.state

case "${1:-}" in
  pull)
    if git ls-remote --exit-code --heads "$REMOTE" state >/dev/null 2>&1; then
      git clone -q --depth 1 --branch state "$REMOTE" "$DIR"
    else
      echo "no state branch yet; starting fresh"
      git init -q -b state "$DIR"
      git -C "$DIR" remote add origin "$REMOTE"
    fi
    ;;
  push)
    cd "$DIR"
    git add -A
    if git diff --cached --quiet; then
      echo "state unchanged"
      exit 0
    fi
    git -c user.name="flightwatch" -c user.email="flightwatch@users.noreply.github.com" \
      commit -q -m "state $(date -u +%Y-%m-%dT%H:%MZ)"
    git push -q origin state
    ;;
  *)
    echo "usage: $0 pull|push" >&2
    exit 2
    ;;
esac
