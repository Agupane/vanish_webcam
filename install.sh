#!/usr/bin/env bash
# VanishCam installer for macOS and Linux.
#   curl -LsSf https://raw.githubusercontent.com/Agupane/vanish_webcam/main/install.sh | bash
# or, from a copy of the repo: ./install.sh
set -euo pipefail

REPO="Agupane/vanish_webcam"
# Branch, tag or commit to install. Pinning a tag (VANISHCAM_REF=v1.0.0) is safer than main.
REF="${VANISHCAM_REF:-main}"
TARGET="${VANISHCAM_DIR:-$HOME/VanishCam}"
# Versioned uv installer (its checksum is verified before running it).
UV_VERSION="0.13.6"
UV_INSTALLER_SHA256="f7a56e7afaec49a3bcbc3ac3cdbe917e7c6ce30e0d815308a12e531aa5ef23b7"

say() { printf '\n[VanishCam] %s\n' "$*"; }
fail() { printf '\n[VanishCam] %s\n' "$*" >&2; exit 1; }

sha256() {
  if command -v sha256sum >/dev/null; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

install_uv() {
  local tmp
  tmp="$(mktemp -d)"
  say "Installing uv (installs Python without asking for administrator rights)..."
  if ! curl -fsSL "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/uv-installer.sh" \
       -o "$tmp/uv-installer.sh"; then
    rm -rf "$tmp"
    fail "Could not download the uv installer."
  fi
  if [[ "$(sha256 "$tmp/uv-installer.sh")" != "$UV_INSTALLER_SHA256" ]]; then
    rm -rf "$tmp"
    fail "The uv installer does not match the expected checksum. Not running it."
  fi
  bash "$tmp/uv-installer.sh" || { rm -rf "$tmp"; fail "uv installation failed."; }
  rm -rf "$tmp"
  export PATH="$HOME/.local/bin:$PATH"
}

install_macos() {
  local app_dir="$1" launcher
  cd "$app_dir"
  if [[ "$(uname -m)" == "x86_64" ]]; then
    say "Mac with an Intel processor: using older versions of MediaPipe and OpenCV (experimental support)."
  fi

  if ! command -v uv >/dev/null; then
    install_uv
  fi

  say "Setting up Python and the dependencies..."
  [[ -x .venv/bin/python ]] || uv venv --python 3.12 .venv
  uv pip install --python .venv/bin/python --require-hashes -r requirements.lock.txt

  say "Downloading MediaPipe models..."
  .venv/bin/python -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" "$app_dir"

  if [[ ! -d /Applications/OBS.app ]]; then
    if command -v brew >/dev/null; then
      say "Installing OBS Studio (it includes the virtual camera)..."
      brew install --cask obs
    else
      say "OBS Studio, which includes the virtual camera, is missing. Download it from https://obsproject.com/download,"
      say "install it and run this installer again."
      open "https://obsproject.com/download" || true
      exit 1
    fi
  fi

  say "Creating the VanishCam shortcut on the Desktop..."
  launcher="$HOME/Desktop/VanishCam.command"
  printf '#!/bin/bash\ncd %q && ./vanishcam.sh\n' "$app_dir" > "$launcher"
  chmod +x "$launcher" "$app_dir"/*.sh

  cat <<'EOF'

[VanishCam] Done. One more step, needed only once, to enable OBS's virtual camera:
  1. Open OBS Studio.
  2. Click "Start Virtual Camera" and accept the permission macOS asks for
     (System Settings → General → Login Items & Extensions → Camera Extensions).
  3. Click "Stop Virtual Camera" and quit OBS.

Then open VanishCam by double-clicking VanishCam.command (Desktop) or with ./vanishcam.sh.
The first time, macOS asks for permission to use the camera: allow it.
In Zoom or Meet pick the "OBS Virtual Camera" camera.
EOF
}

main() {
  local script_dir="" tmp
  if [[ -n "${BASH_SOURCE[0]:-}" && -f "${BASH_SOURCE[0]}" ]]; then
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  fi

  # Run via curl | bash: download the repo and continue from there.
  if [[ -z $script_dir || ! -f "$script_dir/vanish_cam.py" ]]; then
    say "Downloading VanishCam ($REF) to $TARGET..."
    tmp="$(mktemp -d)"
    if ! curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" -o "$tmp/vanishcam.tar.gz"; then
      rm -rf "$tmp"
      fail "Could not download $REPO ($REF)."
    fi
    mkdir -p "$TARGET"
    # Extracts over a previous install without deleting .venv or models/.
    if ! tar -xzf "$tmp/vanishcam.tar.gz" -C "$TARGET" --strip-components=1; then
      rm -rf "$tmp"
      fail "The downloaded archive is not valid."
    fi
    rm -rf "$tmp"
    chmod +x "$TARGET"/*.sh
    exec bash "$TARGET/install.sh"
  fi

  case "$(uname -s)" in
    Linux)
      command -v apt-get >/dev/null \
        || fail "On Linux there is only an installer for Ubuntu/Debian (apt) for now. See the README to do it by hand."
      exec bash "$script_dir/install-ubuntu.sh"
      ;;
    Darwin) install_macos "$script_dir" ;;
    *) fail "Unsupported system: $(uname -s). On Windows use install.ps1." ;;
  esac
}

# Everything is inside main: if the curl | bash download is cut short, a half-downloaded script does not run.
main "$@"
