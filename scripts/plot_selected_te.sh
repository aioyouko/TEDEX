#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

SAMPLES=(
  CHY-1036-A
  CHY-1040-A
  CHY-1040-B
  CHY-1054-A
)

Y_LIMITS=(
  --ylim power_factor 0 15
  --ylim conductivity 0 300
)

python main.py plot-te \
  "${SAMPLES[@]}" \
  --plot-mode both \
  --formats svg png \
  "${Y_LIMITS[@]}" \
  "$@"
