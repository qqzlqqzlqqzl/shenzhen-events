#!/usr/bin/env bash
# Preserve historical output outside the fresh upload set; never delete it.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
: "${RUNNER_TEMP:?RUNNER_TEMP must identify an owned retention directory}"
if [[ -e "$ROOT/artifacts" || -L "$ROOT/artifacts" ]]; then
  retained="$(mktemp -d "$RUNNER_TEMP/events-retained.XXXXXXXX")"
  mv -- "$ROOT/artifacts" "$retained/artifacts"
  printf 'Retained previous artifacts: %s/artifacts\n' "$retained"
fi
mkdir -p -- "$ROOT/artifacts/ci"
