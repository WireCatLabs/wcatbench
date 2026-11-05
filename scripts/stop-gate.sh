#!/usr/bin/env bash
# Stop hook: run the repo's real gate before an agent's "I'm finished" is accepted.
#
# WHY : "the agent says it is finished" is not the same claim as "the
# checks passed". Prose asking an agent to run tests degrades exactly when context fills,
# which is when several sessions are running. This does not degrade.
#
# Exit 0  gate passed, stopping is fine.
# Exit 2  blocking error — stderr is fed back to the model so it can fix and retry.
#
# Reads the hook payload on stdin.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 0

payload="$(cat 2>/dev/null || true)"

# Loop protection. When a Stop hook blocks, the model runs again and stops again; without
# this the pair can ping-pong forever on a failure the model cannot fix.
if printf '%s' "$payload" | grep -q '"stop_hook_active"[[:space:]]*:[[:space:]]*true'; then
  exit 0
fi

# Nothing to check if the toolchain is not installed (fresh clone, CI image without uv).
command -v task >/dev/null 2>&1 || exit 0
[ -d .venv ] || exit 0

if out="$(task gate 2>&1)"; then
  exit 0
fi

{
  echo "wcatbench gate FAILED — not finished yet."
  echo
  printf '%s\n' "$out" | tail -40
  echo
  echo "Fix these, then stop again. Run locally with: task gate"
} >&2
exit 2
