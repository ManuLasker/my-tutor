#!/usr/bin/env bash
# Install the tutor skill for Claude Code and every tool that reads ~/.agents/skills
# (GitHub Copilot, OpenAI Codex, Cursor, Gemini CLI).
#
#   ./install.sh                 symlink into ~/.claude/skills and ~/.agents/skills
#   ./install.sh --copy          copy instead of symlink (no auto-update via git pull)
#   ./install.sh --project DIR   install into DIR/.claude/skills and DIR/.agents/skills
#   ./install.sh --only claude|agents   just one of the two locations
#   ./install.sh --force         replace an existing different install (moved aside, not deleted)
#
# The installed folder must be named "tutor" (the Stop hook looks for it there).
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/skills/tutor"
MODE=link BASE="$HOME" ONLY="" FORCE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --copy) MODE=copy ;;
    --project) BASE="$(cd "${2:?--project needs a directory}" && pwd)"; shift ;;
    --only) ONLY="${2:?--only needs claude or agents}"; shift ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -f "$SRC/SKILL.md" ] || { echo "skill not found at $SRC" >&2; exit 1; }
PY="$(command -v python3 || command -v python || true)"
[ -n "$PY" ] || echo "warning: python3 not found; the tutor's scripts need Python 3.8+" >&2

targets=()
[ "$ONLY" != agents ] && targets+=("$BASE/.claude/skills")
[ "$ONLY" != claude ] && targets+=("$BASE/.agents/skills")

done_dirs=()
for parent in "${targets[@]}"; do
  mkdir -p "$parent"
  real_parent="$(cd "$parent" && pwd -P)"
  # ~/.claude/skills and ~/.agents/skills may be the same folder (symlinked)
  for d in "${done_dirs[@]:-}"; do
    [ "$d" = "$real_parent" ] && { echo "skip  $parent (same folder as an earlier target)"; continue 2; }
  done
  done_dirs+=("$real_parent")
  dest="$parent/tutor"

  if [ -L "$dest" ] && [ "$(cd "$dest" && pwd -P)" = "$(cd "$SRC" && pwd -P)" ]; then
    echo "ok    $dest (already linked to this repo)"
    continue
  fi
  if [ -e "$dest" ] || [ -L "$dest" ]; then
    if [ "$FORCE" -ne 1 ]; then
      echo "exists $dest (a different install); rerun with --force to replace it" >&2
      continue
    fi
    # outside the skills folder, or tools would load two skills named "tutor"
    aside="$HOME/.tutor-install-backups/tutor-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$HOME/.tutor-install-backups"
    mv "$dest" "$aside"
    echo "moved old install to $aside"
  fi
  if [ "$MODE" = link ]; then
    ln -s "$SRC" "$dest"
    echo "link  $dest -> $SRC"
  else
    cp -R "$SRC" "$dest"
    find "$dest" -name __pycache__ -prune -exec rm -rf {} +
    echo "copy  $dest"
  fi
done

if [ -n "$PY" ]; then
  "$PY" "$SRC/scripts/topics.py" init
fi

cat <<'EOF'

Done. Next:
  - Claude Code: run /tutor <topic> (restart Claude Code if it was open).
  - Copilot / Codex / Cursor / Gemini: ask "teach me <topic>" or invoke the tutor skill.
  - Optional settings in ~/.config/tutor/config.json:
      {"home": "~/Documents/learning", "bind": "127.0.0.1"}
    ("bind": "0.0.0.0" serves the study viewer to your whole LAN.)
EOF
