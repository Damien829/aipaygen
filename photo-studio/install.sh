#!/bin/bash
# ProTune installer for macOS (also works on Linux, minus the app icon).
# Safe to run again: that's also how you update after downloading a new version.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="$HOME/.protune"
VENV="$HOME_DIR/venv"
BIN="$HOME/.local/bin"
mkdir -p "$HOME_DIR" "$BIN"

say() { printf "\n\033[1m%s\033[0m\n" "$*"; }
ok() { printf "  ✓ %s\n" "$*"; }
note() { printf "  • %s\n" "$*"; }

say "Installing ProTune"

# 1. uv: gets a private, up-to-date Python (macOS doesn't ship a usable one).
UV="$(command -v uv || true)"
[ -z "$UV" ] && [ -x "$BIN/uv" ] && UV="$BIN/uv"
if [ -z "$UV" ]; then
  note "Downloading uv (Python manager)…"
  curl -LsSf https://astral.sh/uv/install.sh | env UV_NO_MODIFY_PATH=1 sh >/dev/null
  UV="$BIN/uv"
fi
ok "uv ready"

# 2. Python + ProTune in its own folder (~/.protune), nothing system-wide.
if [ ! -x "$VENV/bin/python" ]; then
  "$UV" venv --quiet --python 3.12 "$VENV"
fi
"$UV" pip install --quiet --python "$VENV/bin/python" --reinstall-package protune "$HERE"
ln -sf "$VENV/bin/protune" "$BIN/protune"
ln -sf "$VENV/bin/protune-app" "$BIN/protune-app"
ok "ProTune $("$VENV/bin/protune" --version | awk '{print $2}') installed"

# 3. ExifTool: copies camera details (date, lens, GPS, copyright) into your edits.
if command -v exiftool >/dev/null || [ -x "$BIN/exiftool" ] || [ -x /opt/homebrew/bin/exiftool ]; then
  ok "ExifTool found"
else
  note "Downloading ExifTool…"
  if VER="$(curl -fsSL https://exiftool.org/ver.txt)" && \
     curl -fsSL "https://exiftool.org/Image-ExifTool-${VER}.tar.gz" | tar xz -C "$HOME_DIR"; then
    ln -sf "$HOME_DIR/Image-ExifTool-${VER}/exiftool" "$BIN/exiftool"
    ok "ExifTool $VER installed"
  else
    note "Couldn't download ExifTool. Edits still work, but RAW edits won't carry camera details."
    note "To add it later: brew install exiftool   (or re-run this installer)"
  fi
fi

# 4. The app (Mac only).
if [ "$(uname)" = "Darwin" ]; then
  mkdir -p "$HOME/Applications"
  APP="$("$VENV/bin/python" -m protune.macapp)"
  ok "App created: $APP  (also in Spotlight: type ProTune)"
fi

# 5. Claude Code: needed only for AI fine-tuning (uses your Claude plan).
CLAUDE=""
for c in "$(command -v claude || true)" "$BIN/claude" "$HOME/.claude/local/claude" /opt/homebrew/bin/claude /usr/local/bin/claude; do
  [ -n "$c" ] && [ -x "$c" ] && CLAUDE="$c" && break
done
if [ -n "$CLAUDE" ]; then
  ok "Claude Code found"
else
  say "AI fine-tuning needs Claude Code (included with your Claude Pro plan)."
  read -r -p "  Install Claude Code now? [Y/n] " yn </dev/tty 2>/dev/null || yn="n"
  if [ -z "$yn" ] || [[ "$yn" =~ ^[Yy] ]]; then
    curl -fsSL https://claude.ai/install.sh | bash
    CLAUDE="$BIN/claude"
  else
    note "Skipped. ProTune still edits photos automatically, without the AI review."
  fi
fi

case ":$PATH:" in *":$BIN:"*) ;; *)
  SHELL_RC="$HOME/.zshrc"; [ "$(basename "${SHELL:-zsh}")" = "bash" ] && SHELL_RC="$HOME/.bash_profile"
  grep -qs 'protune: add ~/.local/bin' "$SHELL_RC" || \
    printf '\n# protune: add ~/.local/bin to PATH\nexport PATH="$HOME/.local/bin:$PATH"\n' >> "$SHELL_RC"
  note "Added ~/.local/bin to your PATH (new Terminal windows will find the protune command)."
esac

say "All done."
if [ -n "$CLAUDE" ]; then
  echo "  One last step if you haven't yet: log in to Claude Code with your Claude account."
  echo "  In Terminal, type:  claude    then follow the login steps, then type /exit"
fi
if [ "$(uname)" = "Darwin" ]; then
  echo "  Open ProTune from Applications (or Spotlight). It opens in your web browser."
else
  echo "  Start it with:  protune-app"
fi
