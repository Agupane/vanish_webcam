#!/usr/bin/env bash
# Instala VanishCam en Ubuntu 22.04/24.04: dependencias, entorno Python,
# modelos de MediaPipe y la cámara virtual (v4l2loopback) para Zoom y Meet.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
CAM_LABEL="VanishCam"
CAM_NR=10
# Versión oficial que se compila si la de Ubuntu no anda con el kernel instalado.
V4L2LOOPBACK_VERSION=0.13.2
# Commit del tag v0.13.2: si el tag se moviera, no se compila (es código que corre en el kernel).
V4L2LOOPBACK_COMMIT=2d44c2f3a33844dfd9928dc536288283289bbc34

say() { printf '\n[VanishCam] %s\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
  echo "Correlo como tu usuario normal (el script pide sudo cuando hace falta)." >&2
  exit 1
fi

say "Instalando paquetes del sistema..."
# Un repositorio de terceros roto (firma vencida) no tiene que frenar la instalación.
sudo apt-get update || say "Aviso: apt-get update tuvo errores; sigo con los índices que hay."
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  v4l-utils dkms build-essential git \
  libegl1 libgl1 libglib2.0-0 ffmpeg \
  "linux-headers-$(uname -r)"

build_v4l2loopback_from_source() {
  local version="$V4L2LOOPBACK_VERSION" tmp
  say "El paquete v4l2loopback de tu Ubuntu no compila para el kernel $(uname -r)."
  say "Compilo la versión oficial $version (tarda un minuto)..."
  sudo apt-get remove -y v4l2loopback-dkms 2>/dev/null || true
  tmp="$(mktemp -d)"
  git clone -q --depth 1 --branch "v$version" https://github.com/umlaeute/v4l2loopback.git "$tmp/src"
  if [[ "$(git -C "$tmp/src" rev-parse HEAD)" != "$V4L2LOOPBACK_COMMIT" ]]; then
    rm -rf "$tmp"
    echo "[VanishCam] El código de v4l2loopback v$version no coincide con el commit esperado. No lo compilo." >&2
    exit 1
  fi
  sed -i "s/^PACKAGE_VERSION=.*/PACKAGE_VERSION=\"$version\"/" "$tmp/src/dkms.conf"
  sudo dkms remove -m v4l2loopback -v "$version" --all 2>/dev/null || true
  sudo rm -rf "/usr/src/v4l2loopback-$version"
  sudo cp -r "$tmp/src" "/usr/src/v4l2loopback-$version"
  rm -rf "$tmp"
  sudo dkms install -m v4l2loopback -v "$version"
}

if ! modinfo v4l2loopback >/dev/null 2>&1; then
  # El de Ubuntu 22.04 (0.12.7) no compila con los kernels 6.8 o más nuevos.
  if ! sudo apt-get install -y v4l2loopback-dkms || ! modinfo v4l2loopback >/dev/null 2>&1; then
    build_v4l2loopback_from_source
  fi
fi

say "Configurando la cámara virtual '$CAM_LABEL' (/dev/video$CAM_NR)..."
echo "v4l2loopback" | sudo tee /etc/modules-load.d/vanishcam.conf >/dev/null
echo "options v4l2loopback devices=1 video_nr=$CAM_NR card_label=\"$CAM_LABEL\" exclusive_caps=1" \
  | sudo tee /etc/modprobe.d/vanishcam.conf >/dev/null
if ! [[ -e /sys/devices/virtual/video4linux/video$CAM_NR ]]; then
  # Si ya estaba cargado con otras opciones, se recarga con las nuestras.
  if lsmod | grep -q '^v4l2loopback'; then
    say "Recargo v4l2loopback: si OBS u otra app usaba una cámara virtual, cerrala antes."
  fi
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
Exec="$APP_DIR/vanishcam.sh"
Icon=camera-web
Terminal=true
Categories=AudioVideo;Video;
EOF

say "Listo. Arrancalo con ./vanishcam.sh (o desde el menú: VanishCam)"
say "En Zoom o Meet elegí la cámara '$CAM_LABEL'."
