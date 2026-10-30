#!/bin/bash
# Deploy Expo web app to agent-service static directory
# Preserves custom index.html, manifest.json, and fonts

set -e

SRC="/home/damien809/aipaygen-app/dist"
DEST="/home/damien809/agent-service/static/app"

# Save custom files
cp "$DEST/index.html" /tmp/app-index-backup.html 2>/dev/null || true
cp "$DEST/manifest.json" /tmp/app-manifest-backup.json 2>/dev/null || true

# Clean and copy new build
rm -rf "$DEST"/*
cp -r "$SRC"/* "$DEST"/

# Restore custom files
cp /tmp/app-index-backup.html "$DEST/index.html"
cp /tmp/app-manifest-backup.json "$DEST/manifest.json"

# Update JS bundle hash in index.html
NEW_JS=$(ls "$DEST/_expo/static/js/web/" | head -1)
if [ -n "$NEW_JS" ]; then
  sed -i "s|entry-[a-f0-9]\{32\}\.js|$NEW_JS|g" "$DEST/index.html"
  echo "Updated JS bundle: $NEW_JS"
fi

# Update CSS hash if changed
NEW_CSS=$(ls "$DEST/_expo/static/css/" | head -1)
if [ -n "$NEW_CSS" ]; then
  sed -i "s|web-[a-f0-9]\{32\}\.css|$NEW_CSS|g" "$DEST/index.html"
  echo "Updated CSS bundle: $NEW_CSS"
fi

echo "Deploy complete!"
