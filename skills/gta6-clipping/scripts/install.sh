#!/usr/bin/env bash
# Links this skill into ~/.claude/skills so Claude Code finds it. Never overwrites or deletes.
set -euo pipefail

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
SKILLS="$HOME/.claude/skills"
TARGET="$SKILLS/gta6-clipping"

mkdir -p "$SKILLS"
if [ -L "$TARGET" ]; then
  CURRENT="$(cd "$TARGET" 2>/dev/null && pwd -P || true)"
  if [ "$CURRENT" = "$SKILL_DIR" ]; then
    echo "Skill already installed: $TARGET -> $SKILL_DIR"
    exit 0
  fi
  echo "Refusing: $TARGET points elsewhere ($(readlink "$TARGET")); remove it yourself, then re-run." >&2
  exit 1
fi
if [ -e "$TARGET" ]; then
  echo "Refusing: $TARGET already exists and is not a link to this skill; move it yourself, then re-run." >&2
  exit 1
fi
ln -s "$SKILL_DIR" "$TARGET"
echo "Installed: $TARGET -> $SKILL_DIR"
