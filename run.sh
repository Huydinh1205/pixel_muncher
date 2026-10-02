#!/usr/bin/env bash
# Start the Pixel Muncher GUI.
#   ./run.sh           production on the GPU workstation (config.yaml)
#   ./run.sh --check   check config.yaml (paths, models, GPU) and exit
#   ./run.sh --mock    demo with fake data and fake tools (config.mock.yaml)
#   ./run.sh --local   your own .tif files in local_data/, real tiling, fake classification
set -euo pipefail
cd "$(dirname "$0")"
PY="${PXM_GUI_PYTHON:-}"
if [[ -z "$PY" ]]; then
  if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else PY=python3; fi
fi
case "${1:-}" in
  --mock)  "$PY" mock/setup_demo.py ;;
  --local) "$PY" mock/setup_demo.py --models-only
           set -- --config config.local.yaml ;;
esac
exec "$PY" app.py "$@"
