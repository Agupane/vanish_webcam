#!/usr/bin/env bash
# Arranca VanishCam mandando el video a la cámara virtual (v4l2loopback en Linux, OBS en macOS).
# Acepta las mismas opciones que vanish_cam.py, p. ej. --mode naruto o --camera /dev/video2.
# En Linux, --sonido-en-llamada crea el micrófono "VanishCam-Microfono" (tu micrófono + los efectos).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$APP_DIR/.venv/bin/python"
CAM_LABEL="VanishCam"

if [[ ! -x "$PYTHON" ]]; then
  echo "[VanishCam] Falta instalar: corré ./install.sh" >&2
  exit 1
fi

call_audio=false
args=()
for arg in "$@"; do
  if [[ $arg == --sonido-en-llamada ]]; then
    call_audio=true
  else
    args+=("$arg")
  fi
done

if [[ "$(uname -s)" == Darwin ]]; then
  [[ $call_audio == true ]] && echo "[VanishCam] --sonido-en-llamada todavía no está disponible en macOS (ver README)." >&2
  exec "$PYTHON" "$APP_DIR/vanish_cam.py" --virtual-camera --virtual-backend obs ${args[@]+"${args[@]}"}
fi

# ---------- Linux ----------
device=""
for node in /sys/devices/virtual/video4linux/video*; do
  [[ -e $node ]] || continue
  if [[ $(cat "$node/name" 2>/dev/null) == "$CAM_LABEL" ]]; then
    device="/dev/$(basename "$node")"
    break
  fi
done
if [[ -z $device ]]; then
  echo "[VanishCam] No encuentro la cámara virtual '$CAM_LABEL'. Probá: sudo modprobe v4l2loopback" >&2
  echo "            (o corré ./install.sh de nuevo)" >&2
  exit 1
fi

modules=()
cleanup_call_audio() {
  local index
  for (( index=${#modules[@]}-1; index>=0; index-- )); do
    pactl unload-module "${modules[index]}" 2>/dev/null || true
  done
}

load_module() {
  local id
  id="$(pactl load-module "$@")"
  modules+=("$id")
}

setup_call_audio() {
  local mic speakers
  if ! command -v pactl >/dev/null; then
    echo "[VanishCam] Falta pactl: sudo apt install pulseaudio-utils" >&2
    exit 1
  fi
  mic="$(pactl get-default-source)"
  speakers="$(pactl get-default-sink)"
  if [[ $mic == vanishcam_* ]]; then
    echo "[VanishCam] Tu micrófono por defecto es el de VanishCam: elegí tu micrófono real en Ajustes → Sonido." >&2
    exit 1
  fi
  trap cleanup_call_audio EXIT
  # Los efectos suenan en vanishcam_fx; de ahí van a tus parlantes y a la mezcla.
  # La mezcla junta tu micrófono real con los efectos y sale como un micrófono virtual.
  load_module module-null-sink sink_name=vanishcam_fx sink_properties=device.description=VanishCam-Efectos
  load_module module-null-sink sink_name=vanishcam_mix sink_properties=device.description=VanishCam-Mezcla
  load_module module-loopback source="$mic" sink=vanishcam_mix latency_msec=20
  load_module module-loopback source=vanishcam_fx.monitor sink=vanishcam_mix latency_msec=20
  load_module module-loopback source=vanishcam_fx.monitor sink="$speakers" latency_msec=20
  load_module module-remap-source source_name=vanishcam_mic master=vanishcam_mix.monitor \
    source_properties=device.description=VanishCam-Microfono
  export PULSE_SINK=vanishcam_fx SDL_AUDIODRIVER=pulseaudio
  echo "[VanishCam] Sonido en la llamada: en Zoom o Meet elegí el micrófono 'VanishCam-Microfono'."
  echo "            Bajá la supresión de ruido de Zoom/Meet o puede borrar los efectos."
}

# El OpenCV de pip trae Qt sin soporte Wayland: forzar X11 (XWayland) evita avisos.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

command=("$PYTHON" "$APP_DIR/vanish_cam.py" --virtual-camera --virtual-backend v4l2loopback
         --virtual-device "$device" ${args[@]+"${args[@]}"})
if [[ $call_audio == true ]]; then
  setup_call_audio
  # Sin exec: al salir hay que desarmar el micrófono virtual.
  "${command[@]}"
else
  exec "${command[@]}"
fi
