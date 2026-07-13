#!/usr/bin/env bash
#
# install-sparing-service.sh — pasang SPARING Monitor sebagai systemd service
# yang auto-start saat boot (fullscreen di layar HDMI).
#
# Jalankan DI PERANGKAT (Raspberry Pi / Orange Pi), dari root repo:
#   sudo bash deploy/install-sparing-service.sh
#
# Skrip mendeteksi otomatis: user desktop, lokasi project, dan interpreter
# Python (venv bila ada). Lihat deploy/README.md untuk catatan Wayland.

set -euo pipefail

SERVICE_NAME=sparing
UNIT_PATH="/etc/systemd/system/${SERVICE_NAME}.service"

if [ "$(id -u)" -ne 0 ]; then
  echo "Harus dijalankan dengan sudo:  sudo bash deploy/install-sparing-service.sh" >&2
  exit 1
fi

# Direktori project = induk dari folder deploy/ tempat skrip ini berada
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# User target = pemanggil sudo, fallback ke pemilik folder project
USER_NAME="${SUDO_USER:-$(stat -c '%U' "$DIR")}"

# Python: utamakan venv di dalam project, jika tidak pakai python3 sistem
if   [ -x "$DIR/.venv/bin/python" ]; then PY="$DIR/.venv/bin/python"
elif [ -x "$DIR/venv/bin/python"  ]; then PY="$DIR/venv/bin/python"
else PY="$(command -v python3 || true)"; fi

if [ -z "${PY:-}" ] || [ ! -x "$PY" ]; then
  echo "python3 tidak ditemukan. Install Python 3 dulu." >&2
  exit 1
fi
if [ ! -f "$DIR/main.py" ]; then
  echo "main.py tidak ada di $DIR — jalankan skrip dari dalam repo." >&2
  exit 1
fi

echo "── Konfigurasi terdeteksi ──────────────────────────────"
echo "  User    : $USER_NAME"
echo "  Project : $DIR"
echo "  Python  : $PY"
echo "  Unit    : $UNIT_PATH"
echo "────────────────────────────────────────────────────────"

# Akses port RS485 (USB serial) tanpa root
usermod -aG dialout "$USER_NAME" 2>/dev/null || true

# Tulis unit dari template, substitusi placeholder
sed -e "s|__USER__|$USER_NAME|g" \
    -e "s|__DIR__|$DIR|g" \
    -e "s|__PY__|$PY|g" \
    "$SCRIPT_DIR/sparing.service" > "$UNIT_PATH"

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
systemctl restart "$SERVICE_NAME"

echo
echo "✓ Service '$SERVICE_NAME' terpasang & aktif."
echo "  Status : systemctl status $SERVICE_NAME"
echo "  Log    : journalctl -u $SERVICE_NAME -f"
echo "  Stop   : sudo systemctl stop $SERVICE_NAME"
echo "  Matikan auto-start : sudo systemctl disable $SERVICE_NAME"
echo
systemctl --no-pager --lines=0 status "$SERVICE_NAME" || true
