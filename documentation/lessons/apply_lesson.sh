#!/usr/bin/env bash
# Copy one lesson's files into the project.
#
#   documentation/lessons/apply_lesson.sh 04          # copy lesson 04's files
#   documentation/lessons/apply_lesson.sh 04 --dry-run
#
# Every lesson's files/ folder mirrors the project root and holds only the files that are
# new or changed in that lesson, in full. Apply lessons in order.
#
# Files you fill in by hand (deploy/environments.yaml and your design records) are NEVER
# overwritten if they already exist. The script tells you to compare them instead.
# deploy/<env>.env is written by terraform apply, so no lesson ships it.
set -euo pipefail

usage() { echo "usage: $0 <lesson number> [--dry-run]"; exit 1; }
[ $# -ge 1 ] || usage
N=$(printf "%02d" "$((10#$1))")
DRY_RUN=${2:-}

ROOT=$(git rev-parse --show-toplevel)
SRC="$ROOT/documentation/lessons/lesson$N/files"
[ -d "$SRC" ] || { echo "No files for lesson $N (reading lessons have none)."; exit 0; }

PROTECTED='^(deploy/[a-z]+\.env|deploy/environments\.yaml|documentation/design/[A-Za-z_]+\.md)$'

cd "$SRC"
find . -type f | sed 's|^\./||' | sort | while read -r f; do
  if [[ "$f" =~ $PROTECTED ]] && [ -e "$ROOT/$f" ]; then
    echo "kept     $f   (yours: compare with  diff \"$SRC/$f\" \"$ROOT/$f\")"
    continue
  fi
  if [ -e "$ROOT/$f" ]; then action="updated "; else action="added   "; fi
  echo "$action $f"
  if [ "$DRY_RUN" != "--dry-run" ]; then
    mkdir -p "$ROOT/$(dirname "$f")"
    cp -p "$f" "$ROOT/$f"
  fi
done
