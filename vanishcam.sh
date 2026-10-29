#!/usr/bin/env bash
# Arranca VanishCam mandando el video a la cámara virtual de v4l2loopback.
# Acepta las mismas opciones que vanish_cam.py, p. ej. --mode naruto o --camera /dev/video2.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$APP_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "[VanishCam] Falta instalar: corré ./install-ubuntu.sh" >&2
  exit 1
fi

# La salida es el dispositivo de v4l2loopback llamado "VanishCam" o, si no, el primero.
device=""
for node in /sys/devices/virtual/video4linux/video*; do
  [[ -e $node ]] || continue
  if [[ $(cat "$node/name" 2>/dev/null) == VanishCam ]]; then
    device="/dev/$(basename "$node")"
    break
  fi
  device="${device:-/dev/$(basename "$node")}"
done
if [[ -z $device ]]; then
  echo "[VanishCam] La cámara virtual no está cargada. Probá: sudo modprobe v4l2loopback" >&2
  echo "            (o corré ./install-ubuntu.sh)" >&2
  exit 1
fi

# El OpenCV de pip trae Qt sin soporte Wayland: forzar X11 (XWayland) evita avisos.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

exec "$PYTHON" "$APP_DIR/vanish_cam.py" \
  --virtual-camera --virtual-backend v4l2loopback --virtual-device "$device" "$@"
