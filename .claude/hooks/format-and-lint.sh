#!/usr/bin/env bash
# PostToolUse (Edit|Write): ruff-format the edited .py file, then lint it.
# Lint errors exit 2 so they go back to Claude to fix.
file=$(jq -r '.tool_input.file_path // empty')
case "$file" in *.py) ;; *) exit 0 ;; esac
[ -f "$file" ] || exit 0
ruff="$CLAUDE_PROJECT_DIR/.venv/bin/ruff"
"$ruff" format --quiet "$file"
if ! out=$("$ruff" check --fix --quiet "$file" 2>&1); then
  echo "ruff found problems in $file:" >&2
  echo "$out" >&2
  exit 2
fi
exit 0
