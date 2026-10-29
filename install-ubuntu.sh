#!/usr/bin/env bash
# Instala VanishCam en Ubuntu 22.04/24.04: dependencias, entorno Python,
# modelos de MediaPipe y la cámara virtual (v4l2loopback) para Zoom y Meet.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
CAM_LABEL="VanishCam"
CAM_NR=10

say() { printf '\n[VanishCam] %s\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
  echo "Correlo como tu usuario normal (el script pide sudo cuando hace falta)." >&2
  exit 1
fi

say "Instalando paquetes del sistema..."
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  v4l2loopback-dkms v4l-utils \
  libegl1 libgl1 libglib2.0-0 ffmpeg \
  "linux-headers-$(uname -r)"

say "Configurando la cámara virtual '$CAM_LABEL' (/dev/video$CAM_NR)..."
echo "v4l2loopback" | sudo tee /etc/modules-load.d/vanishcam.conf >/dev/null
echo "options v4l2loopback devices=1 video_nr=$CAM_NR card_label=\"$CAM_LABEL\" exclusive_caps=1" \
  | sudo tee /etc/modprobe.d/vanishcam.conf >/dev/null
if ! [[ -e /sys/devices/virtual/video4linux/video$CAM_NR ]]; then
  # Si ya estaba cargado con otras opciones, se recarga con las nuestras.
  sudo modprobe -r v4l2loopback 2>/dev/null || true
  if ! sudo modprobe v4l2loopback; then
    cat >&2 <<'EOF'

No se pudo cargar v4l2loopback. Si tenés Secure Boot activo, reiniciá:
aparece una pantalla azul (MOK) para inscribir la clave con la contraseña
que te pidió apt. Después volvé a correr este script.
EOF
    exit 1
  fi
fi

say "Creando el entorno Python en .venv..."
[[ -x "$VENV_DIR/bin/python" ]] || python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

say "Descargando modelos de MediaPipe..."
"$VENV_DIR/bin/python" -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" "$APP_DIR"

say "Agregando VanishCam al menú de aplicaciones..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/vanishcam.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VanishCam
Comment=Efectos de desaparición para la webcam (Zoom, Meet)
Exec=$APP_DIR/vanishcam.sh
Icon=camera-web
Terminal=true
Categories=AudioVideo;Video;
EOF

say "Listo. Arrancalo con ./vanishcam.sh (o desde el menú: VanishCam)"
say "En Zoom o Meet elegí la cámara '$CAM_LABEL'."
