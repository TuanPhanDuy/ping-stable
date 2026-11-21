#!/bin/sh
# Cài pingstable trên macOS: curl -fsSL https://github.com/TuanPhanDuy/ping-stable/releases/latest/download/install.sh | sh
set -eu

REPO="TuanPhanDuy/ping-stable"
VERSION="${PINGSTABLE_VERSION:-latest}"
DEST="${PINGSTABLE_DIR:-$HOME/.local/bin}"

[ "$(uname -s)" = "Darwin" ] || { echo "install.sh chỉ dành cho macOS. Windows: dùng install.ps1"; exit 1; }

case "$(uname -m)" in
  arm64) ASSET="pingstable-macos-arm64" ;;
  x86_64) ASSET="pingstable-macos-x64" ;;
  *) echo "Không hỗ trợ CPU $(uname -m)"; exit 1 ;;
esac

if [ "$VERSION" = "latest" ]; then
  BASE="https://github.com/$REPO/releases/latest/download"
else
  BASE="https://github.com/$REPO/releases/download/$VERSION"
fi

mkdir -p "$DEST"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

echo "Đang tải $ASSET..."
if curl -fsSL -o "$TMP" "$BASE/$ASSET"; then
  install -m 755 "$TMP" "$DEST/pingstable"
elif command -v python3 >/dev/null 2>&1; then
  echo "Không có bản build cho máy này, dùng bản Python thay thế."
  curl -fsSL -o "$TMP" "$BASE/pingstable.py"
  install -m 755 "$TMP" "$DEST/pingstable"
else
  echo "Không tải được $ASSET và máy không có python3."; exit 1
fi

echo "Đã cài: $DEST/pingstable ($("$DEST/pingstable" --version))"

case ":$PATH:" in
  *":$DEST:"*) ;;
  *)
    RC="$HOME/.zshrc"
    LINE="export PATH=\"$DEST:\$PATH\""
    grep -qsF "$LINE" "$RC" || printf '\n%s\n' "$LINE" >> "$RC"
    echo "Đã thêm $DEST vào PATH trong $RC. Mở terminal mới hoặc chạy: source $RC"
    ;;
esac

echo "Thử ngay: pingstable wifi"
