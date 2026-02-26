#!/usr/bin/env bash
set -euo pipefail

BOT_REPO=""
SKILL_ID=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bot-repo)
      BOT_REPO="$2"
      shift 2
      ;;
    --skill-id)
      SKILL_ID="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$BOT_REPO" || -z "$SKILL_ID" ]]; then
  echo "Usage: $0 --bot-repo /path/to/bot --skill-id <id>" >&2
  exit 1
fi

SRC_DIR="skills/${SKILL_ID}"
DST_DIR="${BOT_REPO}/skills/${SKILL_ID}"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Skill not found: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "${BOT_REPO}/skills"
rm -rf "$DST_DIR"
cp -R "$SRC_DIR" "$DST_DIR"

echo "Published skill '${SKILL_ID}' to '${DST_DIR}'"
echo "Restart bot process to reload skills."
