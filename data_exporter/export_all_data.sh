#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON="$(command -v python)"
else
  echo "Error: no Python interpreter found. Install Python or create a virtual environment."
  exit 1
fi

AOI_SWEEP_DEGREES="${AOI_SWEEP_DEGREES:-30}"
AOI_SWEEP_STEP="${AOI_SWEEP_STEP:-1}"
BROWSER_MODE="headless"
for arg in "$@"; do
  if [[ "$arg" == "--headed" ]]; then
    BROWSER_MODE="headed"
    break
  fi
done

SOURCE="${DATA_SOURCE:-}"
if [[ -z "$SOURCE" ]]; then
  echo "Select data source:"
  echo "  1) searchlight"
  read -r -p "Source [searchlight]: " SOURCE
  SOURCE="${SOURCE:-searchlight}"
fi

case "$SOURCE" in
  1|searchlight|SearchLight|SEARCHLIGHT)
    SOURCE="searchlight"
    ;;
  *)
    echo "Error: unsupported data source '$SOURCE'. Available option: searchlight"
    exit 1
    ;;
esac

echo "Data exporter"
echo "Project: $SCRIPT_DIR"
echo "Python: $($PYTHON --version)"
echo "Source: $SOURCE"
echo "Browser: $BROWSER_MODE"
echo "AOI sweep: +/-${AOI_SWEEP_DEGREES} degrees, step ${AOI_SWEEP_STEP} degree(s)"
echo

"$PYTHON" -m data_exporter.exporter \
  --all \
  --source "$SOURCE" \
  --aoi-sweep "$AOI_SWEEP_DEGREES" "$AOI_SWEEP_STEP" \
  "$@"
