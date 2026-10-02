#!/bin/bash
# Build "Pixel Muncher.app" so the app can be started from Finder, Launchpad or the Dock.
#
#   bash launchers/macos/make_app.sh            # --local mode (your .tif files)
#   bash launchers/macos/make_app.sh --mock     # demo mode
#   bash launchers/macos/make_app.sh --prod     # production config (config.yaml)
#
# The app is created in the repository folder. Keep it there (or drag an alias
# of it to the Dock). If you move the repository, run this script again.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
MODE="--local"
REPO_PATH_FOR_APP="$REPO"
while [ $# -gt 0 ]; do
  case "$1" in
    --local|--mock) MODE="$1" ;;
    --prod) MODE="" ;;
    --repo-path) shift; REPO_PATH_FOR_APP="$1" ;;   # used when building from another machine
    *) echo "unknown option $1"; exit 2 ;;
  esac
  shift
done

APP="$REPO/Pixel Muncher.app"
# files are overwritten in place, so rebuilding works even where deleting is not allowed
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
sed "s|__PXM_MODE__|$MODE|" "$REPO/launchers/macos/launcher.sh" > "$APP/Contents/MacOS/launcher"
chmod +x "$APP/Contents/MacOS/launcher"
cp "$REPO/assets/icon.icns" "$APP/Contents/Resources/icon.icns"
printf '%s' "$REPO_PATH_FOR_APP" > "$APP/Contents/Resources/repo_path"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Pixel Muncher</string>
  <key>CFBundleDisplayName</key><string>Pixel Muncher</string>
  <key>CFBundleIdentifier</key><string>local.pixelmuncher.gui</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>CFBundleShortVersionString</key><string>0.1.3</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>icon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
</dict>
</plist>
PLIST
echo "Created: $APP  (mode: ${MODE:-production})"
