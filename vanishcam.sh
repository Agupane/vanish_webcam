#!/usr/bin/env bash
# Starts VanishCam sending the video to the virtual camera (v4l2loopback on Linux, OBS on macOS).
# Accepts the same options as vanish_cam.py, e.g. --mode naruto or --camera /dev/video2.
# On Linux, --call-audio creates the "VanishCam-Mic" microphone (your microphone + the effects).
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="$APP_DIR/.venv/bin/python"
CAM_LABEL="VanishCam"

if [[ ! -x "$PYTHON" ]]; then
  echo "[VanishCam] Not installed yet: run ./install.sh" >&2
  exit 1
fi

call_audio=false
audio_device=false
args=()
for arg in "$@"; do
  if [[ $arg == --call-audio ]]; then
    call_audio=true
  elif [[ $arg == --audio-device || $arg == --audio-device=* ]]; then
    audio_device=true
    args+=("$arg")
  else
    args+=("$arg")
  fi
done

if [[ $call_audio == true && $audio_device == true ]]; then
  echo "[VanishCam] Use either --call-audio (Linux) or --audio-device, not both." >&2
  exit 1
fi

if [[ "$(uname -s)" == Darwin ]]; then
  [[ $call_audio == true ]] && echo "[VanishCam] --call-audio is not available on macOS yet (see README)." >&2
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
  echo "[VanishCam] Virtual camera '$CAM_LABEL' not found. Try: sudo modprobe v4l2loopback" >&2
  echo "            (or run ./install.sh again)" >&2
  exit 1
fi

# A crashed writer can leave 0.12.7 without VIDEO_OUTPUT capabilities; pyvirtualcam rejects it.
if command -v v4l2-ctl >/dev/null \
   && ! v4l2-ctl -d "$device" --all 2>/dev/null | grep -q "Video Output"; then
  echo "[VanishCam] '$device' exists but is not advertising video output (stale v4l2loopback state)." >&2
  echo "            Reload it: sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback" >&2
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
    echo "[VanishCam] pactl is missing: sudo apt install pulseaudio-utils" >&2
    exit 1
  fi
  mic="$(pactl get-default-source)"
  speakers="$(pactl get-default-sink)"
  if [[ $mic == vanishcam_* ]]; then
    echo "[VanishCam] Your default microphone is VanishCam's: pick your real microphone in Settings → Sound." >&2
    exit 1
  fi
  trap cleanup_call_audio EXIT
  # The effects play into vanishcam_fx; from there they go to your speakers and to the mix.
  # The mix combines your real microphone with the effects and comes out as a virtual microphone.
  load_module module-null-sink sink_name=vanishcam_fx sink_properties=device.description=VanishCam-Effects
  load_module module-null-sink sink_name=vanishcam_mix sink_properties=device.description=VanishCam-Mix
  load_module module-loopback source="$mic" sink=vanishcam_mix latency_msec=20
  load_module module-loopback source=vanishcam_fx.monitor sink=vanishcam_mix latency_msec=20
  load_module module-loopback source=vanishcam_fx.monitor sink="$speakers" latency_msec=20
  load_module module-remap-source source_name=vanishcam_mic master=vanishcam_mix.monitor \
    source_properties=device.description=VanishCam-Mic
  export PULSE_SINK=vanishcam_fx SDL_AUDIODRIVER=pulseaudio
  echo "[VanishCam] Call audio: in Zoom or Meet pick the 'VanishCam-Mic' microphone."
  echo "            Lower Zoom/Meet noise suppression or it may remove the effects."
}

# pip's OpenCV ships Qt without Wayland support: forcing X11 (XWayland) avoids warnings.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"

command=("$PYTHON" "$APP_DIR/vanish_cam.py" --virtual-camera --virtual-backend v4l2loopback
         --virtual-device "$device" ${args[@]+"${args[@]}"})
if [[ $call_audio == true ]]; then
  setup_call_audio
  # No exec: the virtual microphone has to be torn down on exit.
  "${command[@]}"
else
  exec "${command[@]}"
fi
