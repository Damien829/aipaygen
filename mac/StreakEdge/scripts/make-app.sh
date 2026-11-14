#!/bin/bash
# Builds StreakEdge.app in ./build. Run on a Mac with Xcode 15 or newer.
set -euo pipefail
cd "$(dirname "$0")/.."

swift build -c release
APP=build/StreakEdge.app
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$(swift build -c release --show-bin-path)/StreakEdge" "$APP/Contents/MacOS/StreakEdge"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>StreakEdge</string>
    <key>CFBundleIdentifier</key><string>local.streakedge</string>
    <key>CFBundleExecutable</key><string>StreakEdge</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>1.0</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSMinimumSystemVersion</key><string>13.0</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST
codesign --force --sign - "$APP"
echo "Built $APP — open it or drag it to Applications."
