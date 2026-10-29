#!/usr/bin/env bash
# Removes the Ubuntu integration added by install-ubuntu.sh: the virtual camera
# configuration, the DKMS module it built and the Applications menu entry.
# The app folder (.venv, models, code) is kept: delete it by hand if you want.
# Usage: ./uninstall-ubuntu.sh [--yes]
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
V4L2LOOPBACK_VERSION=0.13.2
DESKTOP_FILE="$HOME/.local/share/applications/vanishcam.desktop"

# modinfo, depmod and modprobe live in /usr/sbin, which is not always in a normal user's PATH.
export PATH="$PATH:/usr/sbin:/sbin"

say() { printf '\n[VanishCam] %s\n' "$*"; }
warn() { printf '\n[VanishCam] %s\n' "$*" >&2; }
fail() { warn "$*"; exit 1; }

case "${1:-}" in
  -y | --yes) assume_yes=true ;;
  "") assume_yes=false ;;
  *) fail "Usage: $0 [--yes]" ;;
esac

if [[ $EUID -eq 0 ]]; then
  fail "Run this as your normal user (the script asks for sudo when it needs it)."
fi

say "This will remove:"
printf '  - %s\n' "$DESKTOP_FILE"
printf '  - /etc/modules-load.d/vanishcam.conf\n'
printf '  - /etc/modprobe.d/vanishcam.conf\n'
printf '  - the v4l2loopback %s module built by the installer, if it is present\n' "$V4L2LOOPBACK_VERSION"
printf '  - the loaded v4l2loopback module, if it is not in use\n'
say "It will keep the app folder, .venv, models/, the MOK signing key (shared with other modules)"
say "and Ubuntu's own v4l2loopback package."
if [[ $assume_yes != true ]]; then
  read -r -p "Continue? [y/N] " reply
  [[ $reply == [yY] || $reply == [yY][eE][sS] ]] || { say "Cancelled."; exit 0; }
fi

if [[ -f $DESKTOP_FILE ]]; then
  rm -f "$DESKTOP_FILE"
  say "Removed the Applications menu entry."
fi

for file in /etc/modules-load.d/vanishcam.conf /etc/modprobe.d/vanishcam.conf; do
  if sudo test -f "$file"; then
    sudo rm -f "$file"
    say "Removed $file."
  fi
done

if [[ -d /sys/module/v4l2loopback ]]; then
  if sudo modprobe -r v4l2loopback 2>/dev/null; then
    say "Unloaded v4l2loopback."
  else
    warn "Could not unload v4l2loopback: close OBS or any app using the virtual camera, then run:"
    warn "  sudo modprobe -r v4l2loopback"
  fi
fi

# Only remove the source tree when this installer built it: a distro package can
# ship the same version under /usr/src, and its files must stay.
SOURCE_DIR="/usr/src/v4l2loopback-$V4L2LOOPBACK_VERSION"
if [[ -d $SOURCE_DIR ]] && ! dpkg-query -S "$SOURCE_DIR/dkms.conf" >/dev/null 2>&1; then
  if dkms status -m v4l2loopback -v "$V4L2LOOPBACK_VERSION" 2>/dev/null | grep -q .; then
    sudo dkms remove -m v4l2loopback -v "$V4L2LOOPBACK_VERSION" --all \
      || warn "Could not remove v4l2loopback $V4L2LOOPBACK_VERSION from DKMS."
  fi
  sudo rm -rf "$SOURCE_DIR"
  say "Removed the v4l2loopback $V4L2LOOPBACK_VERSION source built by the installer."
fi

say "Done. The app folder ($APP_DIR) is untouched; delete it to free space: rm -rf \"$APP_DIR\""
