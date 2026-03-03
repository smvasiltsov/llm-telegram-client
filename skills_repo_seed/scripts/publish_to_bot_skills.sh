#!/usr/bin/env bash
set -euo pipefail

MAIN_REPO=""
SKILL_FOLDER=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --main-repo)
      MAIN_REPO="$2"
      shift 2
      ;;
    --skill-folder)
      SKILL_FOLDER="$2"
      shift 2
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [[ -z "$MAIN_REPO" || -z "$SKILL_FOLDER" ]]; then
  echo "Usage: $0 --main-repo /path/to/main/repo --skill-folder <folder>" >&2
  exit 1
fi

SRC_DIR="skills/${SKILL_FOLDER}"
DST_DIR="${MAIN_REPO}/skills/${SKILL_FOLDER}"

if [[ ! -d "$SRC_DIR" ]]; then
  echo "Skill not found: $SRC_DIR" >&2
  exit 1
fi

mkdir -p "${MAIN_REPO}/skills"
rm -rf "$DST_DIR"
cp -R "$SRC_DIR" "$DST_DIR"

echo "Published skill folder '${SKILL_FOLDER}' to '${DST_DIR}'"
