#!/usr/bin/env bash
# Instalador de VanishCam para macOS y Linux.
#   curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
# o, desde una copia del repo: ./install.sh
set -euo pipefail

REPO="Agupane/vanish_webcam"
TARGET="${VANISHCAM_DIR:-$HOME/VanishCam}"

say() { printf '\n[VanishCam] %s\n' "$*"; }
fail() { printf '\n[VanishCam] %s\n' "$*" >&2; exit 1; }

install_macos() {
  local app_dir="$1" launcher
  cd "$app_dir"
  if [[ "$(uname -m)" == "x86_64" ]]; then
    say "Mac con procesador Intel: uso versiones más viejas de MediaPipe y OpenCV (soporte experimental)."
  fi

  if ! command -v uv >/dev/null; then
    say "Instalando uv (instala Python sin pedir permisos de administrador)..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  fi

  say "Preparando Python y las dependencias..."
  [[ -x .venv/bin/python ]] || uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python -r requirements.txt

  say "Descargando modelos de MediaPipe..."
  .venv/bin/python -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" "$app_dir"

  if [[ ! -d /Applications/OBS.app ]]; then
    if command -v brew >/dev/null; then
      say "Instalando OBS Studio (trae la cámara virtual)..."
      brew install --cask obs
    else
      say "Falta OBS Studio, que trae la cámara virtual. Bajalo de https://obsproject.com/download,"
      say "instalalo y volvé a correr este instalador."
      open "https://obsproject.com/download" || true
      exit 1
    fi
  fi

  say "Creando el acceso VanishCam en el Escritorio..."
  launcher="$HOME/Desktop/VanishCam.command"
  printf '#!/bin/bash\ncd %q && ./vanishcam.sh\n' "$app_dir" > "$launcher"
  chmod +x "$launcher" "$app_dir"/*.sh

  cat <<'EOF'

[VanishCam] Listo. Falta un paso, una sola vez, para activar la cámara virtual de OBS:
  1. Abrí OBS Studio.
  2. Tocá "Iniciar cámara virtual" y aceptá el permiso que pide macOS
     (Ajustes del Sistema → General → Ítems de inicio y extensiones → Extensiones de cámara).
  3. Tocá "Detener cámara virtual" y cerrá OBS.

Después abrí VanishCam con doble clic en VanishCam.command (Escritorio) o con ./vanishcam.sh.
La primera vez macOS pide permiso para usar la cámara: aceptalo.
En Zoom o Meet elegí la cámara "OBS Virtual Camera".
EOF
}

main() {
  local script_dir="" tmp
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  fi

  # Ejecutado con curl | bash: bajar el repo y seguir desde ahí.
  if [[ -z $script_dir || ! -f "$script_dir/vanish_cam.py" ]]; then
    say "Descargando VanishCam en $TARGET..."
    tmp="$(mktemp -d)"
    curl -fsSL "https://github.com/$REPO/archive/refs/heads/main.tar.gz" | tar -xz -C "$tmp"
    mkdir -p "$TARGET"
    # Copia encima de una instalación anterior sin borrar .venv ni models/.
    cp -R "$tmp"/vanish_webcam-main/. "$TARGET"/
    rm -rf "$tmp"
    chmod +x "$TARGET"/*.sh
    exec bash "$TARGET/install.sh"
  fi

  case "$(uname -s)" in
    Linux)
      command -v apt-get >/dev/null \
        || fail "En Linux por ahora solo hay instalador para Ubuntu/Debian (apt). Mirá el README para hacerlo a mano."
      exec bash "$script_dir/install-ubuntu.sh"
      ;;
    Darwin) install_macos "$script_dir" ;;
    *) fail "Sistema no soportado: $(uname -s). En Windows usá install.ps1." ;;
  esac
}

# Todo adentro de main: si la descarga con curl | bash se corta, no se ejecuta un script a medias.
main "$@"
