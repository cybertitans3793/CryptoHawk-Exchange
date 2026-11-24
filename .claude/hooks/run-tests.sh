#!/usr/bin/env bash
# Stop: the test suite must pass before Claude finishes a turn in this repo.
# Skips when nothing under main.py/templates/tests changed, and never re-blocks a
# stop it already blocked once (stop_hook_active), so it can't loop forever.
input=$(cat)
[ "$(jq -r '.stop_hook_active // false' <<<"$input")" = "true" ] && exit 0
cd "$CLAUDE_PROJECT_DIR" || exit 0
[ -z "$(git status --porcelain -- main.py templates tests pyproject.toml)" ] && exit 0
if ! out=$(.venv/bin/pytest -x 2>&1); then
  echo "Tests are failing. Fix them (or say why not) before finishing:" >&2
  echo "$out" | tail -40 >&2
  exit 2
fi
exit 0
