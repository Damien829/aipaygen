#!/bin/bash
# Builds "AIPayGen Control.app" with the Swift command line tools (no Xcode needed;
# swiftc directly, because SwiftPM needs full Xcode).
#   ./build.sh        build
#   ./build.sh run    build and open
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .build
swiftc -O -parse-as-library -target "$(uname -m)-apple-macos13.0" Sources/AIPayGenControl/*.swift -o .build/AIPayGenControl
APP="build/AIPayGen Control.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/AIPayGenControl "$APP/Contents/MacOS/AIPayGenControl"
cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>AIPayGen Control</string>
  <key>CFBundleDisplayName</key><string>AIPayGen Control</string>
  <key>CFBundleIdentifier</key><string>com.aipaygen.control</string>
  <key>CFBundleExecutable</key><string>AIPayGenControl</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
</dict></plist>
PLIST
codesign --force --deep -s - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"
if [ "${1:-}" = "run" ]; then open "$APP"; fi
