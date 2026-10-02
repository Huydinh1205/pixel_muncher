#!/bin/bash
# Add a "Pixel Muncher" icon to the application menu and the desktop (Ubuntu/GNOME/KDE).
#   bash launchers/linux/install_desktop_icon.sh            production
#   bash launchers/linux/install_desktop_icon.sh --local    laptop test mode
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MODE="${1:-}"
chmod +x "$REPO/launchers/linux/open_pixel_muncher.sh"
ENTRY="[Desktop Entry]
Type=Application
Name=Pixel Muncher
Comment=Vegetation classification (Pixel Muncher GUI)
Exec=\"$REPO/launchers/linux/open_pixel_muncher.sh\" $MODE
Icon=$REPO/assets/icon-512.png
Terminal=false
Categories=Graphics;Science;
StartupNotify=true"
APPS="$HOME/.local/share/applications"
mkdir -p "$APPS"
printf '%s\n' "$ENTRY" > "$APPS/pixel-muncher.desktop"
chmod +x "$APPS/pixel-muncher.desktop"
echo "Added to the application menu: $APPS/pixel-muncher.desktop"
DESK="$(xdg-user-dir DESKTOP 2>/dev/null || echo "$HOME/Desktop")"
if [ -d "$DESK" ]; then
  cp "$APPS/pixel-muncher.desktop" "$DESK/pixel-muncher.desktop"
  chmod +x "$DESK/pixel-muncher.desktop"
  gio set "$DESK/pixel-muncher.desktop" metadata::trusted true 2>/dev/null || true
  echo "Added to the desktop: $DESK/pixel-muncher.desktop"
  echo "If Ubuntu shows it as untrusted, right-click it and choose 'Allow Launching'."
fi
