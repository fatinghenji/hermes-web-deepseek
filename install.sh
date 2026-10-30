#!/usr/bin/env bash
# Install the DeepSeek web search plugin into Hermes' user plugin dir.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/web/deepseek"
HERMES_HOME_DIR="${HERMES_HOME:-$HOME/.hermes}"
DEST="$HERMES_HOME_DIR/plugins/web/deepseek"

mkdir -p "$(dirname "$DEST")"
rm -rf "$DEST"
cp -r "$SRC" "$DEST"
echo "✓ Installed to $DEST"
echo
echo "Next steps:"
echo "  1. hermes plugins enable web-deepseek"
echo "  2. hermes config set web.search_backend deepseek"
echo "     (optional: hermes config set web.extract_backend deepseek)"
echo "  3. Ensure DEEPSEEK_API_KEY is in $HERMES_HOME_DIR/.env"
echo "  4. Registering the backend: a running gateway hot-reloads plugins on"
echo "     enable; a long-running desktop app may still need an app restart"
echo "     (web providers register at process start)."
