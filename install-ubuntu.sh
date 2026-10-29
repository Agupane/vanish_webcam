#!/usr/bin/env bash
# Installs VanishCam on Ubuntu 22.04/24.04: dependencies, Python environment,
# MediaPipe models and the virtual camera (v4l2loopback) for Zoom and Meet.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
CAM_LABEL="VanishCam"
CAM_NR=10
# Official version that is built if Ubuntu's does not work with the installed kernel.
V4L2LOOPBACK_VERSION=0.13.2
# Commit of the v0.13.2 tag: if the tag ever moves, it is not built (this is code that runs in the kernel).
V4L2LOOPBACK_COMMIT=2d44c2f3a33844dfd9928dc536288283289bbc34

say() { printf '\n[VanishCam] %s\n' "$*"; }

if [[ $EUID -eq 0 ]]; then
  echo "Run it as your normal user (the script asks for sudo when needed)." >&2
  exit 1
fi

say "Installing system packages..."
# A broken third-party repository (expired signature) must not stop the installation.
sudo apt-get update || say "Warning: apt-get update had errors; continuing with the existing indexes."
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  v4l-utils dkms build-essential git \
  libegl1 libgl1 libglib2.0-0 ffmpeg \
  "linux-headers-$(uname -r)"

build_v4l2loopback_from_source() {
  local version="$V4L2LOOPBACK_VERSION" tmp
  say "Your Ubuntu's v4l2loopback package does not build for kernel $(uname -r)."
  say "Building the official version $version (takes a minute)..."
  sudo apt-get remove -y v4l2loopback-dkms 2>/dev/null || true
  tmp="$(mktemp -d)"
  git clone -q --depth 1 --branch "v$version" https://github.com/umlaeute/v4l2loopback.git "$tmp/src"
  if [[ "$(git -C "$tmp/src" rev-parse HEAD)" != "$V4L2LOOPBACK_COMMIT" ]]; then
    rm -rf "$tmp"
    echo "[VanishCam] The v4l2loopback v$version source does not match the expected commit. Not building it." >&2
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
  # Ubuntu 22.04's (0.12.7) does not build with kernels 6.8 or newer.
  if ! sudo apt-get install -y v4l2loopback-dkms || ! modinfo v4l2loopback >/dev/null 2>&1; then
    build_v4l2loopback_from_source
  fi
fi

say "Configuring the virtual camera '$CAM_LABEL' (/dev/video$CAM_NR)..."
echo "v4l2loopback" | sudo tee /etc/modules-load.d/vanishcam.conf >/dev/null
echo "options v4l2loopback devices=1 video_nr=$CAM_NR card_label=\"$CAM_LABEL\" exclusive_caps=1" \
  | sudo tee /etc/modprobe.d/vanishcam.conf >/dev/null
if ! [[ -e /sys/devices/virtual/video4linux/video$CAM_NR ]]; then
  # If it was already loaded with other options, reload it with ours.
  if lsmod | grep -q '^v4l2loopback'; then
    say "Reloading v4l2loopback: if OBS or another app was using a virtual camera, close it first."
  fi
  sudo modprobe -r v4l2loopback 2>/dev/null || true
  if ! sudo modprobe v4l2loopback; then
    cat >&2 <<'EOF'

Could not load v4l2loopback. If Secure Boot is enabled, reboot:
a blue screen (MOK) appears to enroll the key with the password
apt asked you for. Then run this script again.
EOF
    exit 1
  fi
fi

say "Creating the Python environment in .venv..."
[[ -x "$VENV_DIR/bin/python" ]] || python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/requirements.txt"

say "Downloading MediaPipe models..."
"$VENV_DIR/bin/python" -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" "$APP_DIR"

say "Adding VanishCam to the applications menu..."
mkdir -p "$HOME/.local/share/applications"
cat > "$HOME/.local/share/applications/vanishcam.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VanishCam
Comment=Disappearance effects for your webcam (Zoom, Meet)
Exec="$APP_DIR/vanishcam.sh"
Icon=camera-web
Terminal=true
Categories=AudioVideo;Video;
EOF

say "Done. Start it with ./vanishcam.sh (or from the menu: VanishCam)"
say "In Zoom or Meet pick the '$CAM_LABEL' camera."
