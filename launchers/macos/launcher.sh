#!/bin/bash
# Executable inside "Pixel Muncher.app". Starts the app if it is not running,
# then opens it in its own browser window.
MODE="__PXM_MODE__"
APPDIR="$(cd "$(dirname "$0")/.." && pwd)"
REPO="$(cd "$APPDIR/../.." 2>/dev/null && pwd)"
[ -f "$REPO/run.sh" ] || REPO="$(cat "$APPDIR/Resources/repo_path" 2>/dev/null)"

alert() { osascript -e "display alert \"Pixel Muncher\" message \"$1\" as critical" >/dev/null 2>&1; }

if [ ! -f "$REPO/run.sh" ]; then
  alert "Cannot find the Pixel Muncher folder. Keep the app inside the pixel_muncher folder, or rebuild it with launchers/macos/make_app.sh."
  exit 1
fi
. "$REPO/launchers/common.sh"

CONFIG="$(pxm_config_for_mode "$REPO" "$MODE")"
URL="http://127.0.0.1:$(pxm_port "$CONFIG")"

if ! pxm_is_up "$URL"; then
  PY="$(pxm_find_python "$REPO" "$MODE")" || {
    alert "No Python environment with NiceGUI (and GDAL for local mode) was found. Follow docs/LOCAL_TESTING.md step 3 to create the conda environment 'pxm', then open the app again."
    exit 1
  }
  mkdir -p "$REPO/local_state"
  LOG="$REPO/local_state/app.log"
  (cd "$REPO" && PXM_GUI_PYTHON="$PY" nohup bash run.sh $MODE >"$LOG" 2>&1 &)
  if ! pxm_wait_up "$URL" 90; then
    alert "Pixel Muncher did not start. Details are in local_state/app.log: $(tail -3 "$LOG" | tr -d '"\\')"
    exit 1
  fi
fi

for b in "Google Chrome" "Microsoft Edge" "Brave Browser" "Chromium"; do
  if open -Ra "$b" >/dev/null 2>&1; then
    open -na "$b" --args --app="$URL"
    exit 0
  fi
done
open "$URL"
