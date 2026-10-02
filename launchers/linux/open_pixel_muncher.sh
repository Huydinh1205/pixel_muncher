#!/bin/bash
# Start Pixel Muncher on this Linux machine if it is not running, then open it
# in its own browser window. Used by the desktop icon (install_desktop_icon.sh).
#   open_pixel_muncher.sh            production (config.yaml)
#   open_pixel_muncher.sh --local    laptop test mode
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
. "$REPO/launchers/common.sh"
MODE="${1:-}"
CONFIG="$(pxm_config_for_mode "$REPO" "$MODE")"
URL="http://127.0.0.1:$(pxm_port "$CONFIG")"

notify() { command -v notify-send >/dev/null && notify-send "Pixel Muncher" "$1"; echo "$1"; }

if ! pxm_is_up "$URL"; then
  if [ -z "$MODE" ] && systemctl --user is-enabled pxm-gui >/dev/null 2>&1; then
    systemctl --user start pxm-gui
  else
    PY="$(pxm_find_python "$REPO" "$MODE")" || { notify "No Python environment with NiceGUI found. See README, step 2."; exit 1; }
    STATE="$HOME/.pxm_gui"; mkdir -p "$STATE"
    (cd "$REPO" && PXM_GUI_PYTHON="$PY" nohup bash run.sh $MODE >"$STATE/app.log" 2>&1 &)
  fi
  pxm_wait_up "$URL" 90 || { notify "Pixel Muncher did not start. See ~/.pxm_gui/app.log or: journalctl --user -u pxm-gui"; exit 1; }
fi

for b in google-chrome google-chrome-stable chromium chromium-browser microsoft-edge; do
  if command -v "$b" >/dev/null 2>&1; then
    nohup "$b" --app="$URL" >/dev/null 2>&1 &
    exit 0
  fi
done
if command -v xdg-open >/dev/null 2>&1; then xdg-open "$URL" >/dev/null 2>&1 & exit 0; fi
echo "Pixel Muncher is running at $URL"
