#!/usr/bin/env bash
# Installs VanishCam on Ubuntu 22.04/24.04: system packages, Python environment,
# MediaPipe models and the virtual camera (v4l2loopback) for Zoom and Meet.
# Safe to run again: every step checks what is already done.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$APP_DIR/.venv"
CAM_LABEL="VanishCam"
CAM_NR=10
# Upstream release built when the Ubuntu package does not work with the running kernel.
# 0.13.2 builds on Linux 4.3 to 6.14 (uses strscpy; del_timer_sync is gone in 6.15).
V4L2LOOPBACK_VERSION=0.13.2
# Commit of tag v0.13.2: if the tag ever moved, nothing is built (this code runs in the kernel).
V4L2LOOPBACK_COMMIT=2d44c2f3a33844dfd9928dc536288283289bbc34
# Key that Ubuntu's DKMS signs modules with (Secure Boot).
MOK_DIR=/var/lib/shim-signed/mok
MOK_CERT="$MOK_DIR/MOK.der"
MOK_KEY="$MOK_DIR/MOK.priv"
KERNEL="$(uname -r)"

# modinfo, depmod and modprobe live in /usr/sbin, which is not always in a normal user's PATH.
export PATH="$PATH:/usr/sbin:/sbin"

say() { printf '\n[VanishCam] %s\n' "$*"; }
warn() { printf '\n[VanishCam] %s\n' "$*" >&2; }
fail() { warn "$*"; exit 1; }

if [[ $EUID -eq 0 ]]; then
  fail "Run this as your normal user (the script asks for sudo when it needs it)."
fi

# With `curl ... | bash` stdin is the download, not the keyboard: the Secure Boot password
# prompts (mokutil, debconf) would read EOF and fail. Read from the terminal instead.
if [[ ! -t 0 ]] && { : </dev/tty; } 2>/dev/null; then
  exec </dev/tty
fi

# Result of the virtual camera setup: ok, reboot (Secure Boot key waiting for enrollment) or failed.
CAMERA_STATUS=ok
CAMERA_ERROR=""

pkg_status() {
  dpkg-query -W -f='${db:Status-Status}' "$1" 2>/dev/null || echo not-installed
}

# A failed v4l2loopback-dkms (e.g. 0.12.7 on kernel 6.8) stays half-configured, and then
# every later apt-get install retries its postinst, fails again and stops the installer.
purge_broken_v4l2loopback_package() {
  local status
  status="$(pkg_status v4l2loopback-dkms)"
  case "$status" in
    installed | not-installed | config-files | triggers-*) return 0 ;;
  esac
  say "Removing the broken v4l2loopback-dkms package left by an earlier attempt (state: $status)..."
  sudo dpkg --purge v4l2loopback-dkms \
    || sudo dpkg --purge --force-remove-reinstreq v4l2loopback-dkms \
    || fail "Could not remove v4l2loopback-dkms. Run: sudo dpkg --purge --force-all v4l2loopback-dkms"
  # Finish configuring anything else the failed run left pending.
  sudo dpkg --configure -a || warn "Warning: 'sudo dpkg --configure -a' reported errors (see above)."
}

purge_broken_v4l2loopback_package

say "Installing system packages..."
# A broken third-party repository (expired or missing key) must not stop the installation.
sudo apt-get update || say "Warning: apt-get update had errors; continuing with the package lists I have."
packages=(
  python3 python3-venv python3-pip
  v4l-utils kmod dkms build-essential git mokutil zstd xz-utils
  libegl1 libgl1 libgles2 libglib2.0-0 ffmpeg
)
# Kernel headers are needed to build the virtual camera. If the package for the running kernel
# is no longer in the archive (old kernel, not rebooted after an update), report it later
# instead of aborting the whole installation.
if [[ ! -e "/lib/modules/$KERNEL/build" ]]; then
  if apt-cache show "linux-headers-$KERNEL" >/dev/null 2>&1; then
    packages+=("linux-headers-$KERNEL")
  else
    warn "Warning: the package linux-headers-$KERNEL is not available."
  fi
fi
sudo apt-get install -y "${packages[@]}" || fail "apt-get install failed (see the error above).
If it mentions another package that fails to configure, run 'sudo dpkg --configure -a',
fix or remove that package, and run this installer again."

secure_boot_enabled() {
  local state="" var
  if command -v mokutil >/dev/null; then
    state="$(mokutil --sb-state 2>/dev/null || true)"
    [[ $state == *"SecureBoot enabled"* ]] && return 0
    [[ $state == *"SecureBoot disabled"* ]] && return 1
  fi
  # Fallback: last byte of the SecureBoot EFI variable is 1 when it is on.
  var=/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c
  [[ -r $var ]] && [[ "$(od -An -t u1 "$var" 2>/dev/null | awk '{print $NF}')" == 1 ]]
}

# Create the MOK signing key before building, so DKMS signs the module with it.
ensure_mok_key() {
  # Always check with sudo: the MOK folder may not be readable by the user, and an existing
  # key must never be replaced (other modules, e.g. NVIDIA, are signed with it).
  sudo test -f "$MOK_CERT" && sudo test -f "$MOK_KEY" && return 0
  say "Secure Boot is on: creating the key used to sign the virtual camera module..."
  sudo mkdir -p "$MOK_DIR"
  if command -v update-secureboot-policy >/dev/null; then
    sudo update-secureboot-policy --new-key
  fi
  if ! sudo test -f "$MOK_CERT" && ! sudo test -f "$MOK_KEY"; then
    sudo openssl req -new -x509 -newkey rsa:2048 -nodes -days 36500 -outform DER \
      -keyout "$MOK_KEY" -out "$MOK_CERT" \
      -subj "/CN=$(hostname -s) Secure Boot Module Signature key"
    sudo chmod 600 "$MOK_KEY"
  fi
}

module_signed() {
  [[ -n "$(modinfo -F signer v4l2loopback 2>/dev/null)" ]]
}

# Ubuntu's DKMS (2.8.x) compresses modules (.ko.zst on recent kernels) before signing them,
# so the module can end up unsigned. Sign it here if that happened.
sign_module() {
  local module tmp sign_file
  module="$(modinfo -n v4l2loopback 2>/dev/null)" || return 1
  sign_file="/usr/src/linux-headers-$KERNEL/scripts/sign-file"
  [[ -x $sign_file ]] || sign_file="/lib/modules/$KERNEL/build/scripts/sign-file"
  if [[ ! -x $sign_file ]] && ! sign_file="$(command -v kmodsign)"; then
    warn "Cannot find sign-file or kmodsign to sign the module."
    return 1
  fi
  say "Signing $module with the Secure Boot key..."
  tmp="$(mktemp -d)"
  # Each step is checked: a half-done module must never replace the installed one.
  if ! case "$module" in
         *.ko.zst) zstd -q -d -c "$module" > "$tmp/m.ko" ;;
         *.ko.xz) xz -d -c "$module" > "$tmp/m.ko" ;;
         *.ko.gz) gzip -d -c "$module" > "$tmp/m.ko" ;;
         *.ko) cp "$module" "$tmp/m.ko" ;;
         *) false ;;
       esac \
     || ! sudo "$sign_file" sha512 "$MOK_KEY" "$MOK_CERT" "$tmp/m.ko" \
     || ! case "$module" in
            *.ko.zst) zstd -q -f -19 "$tmp/m.ko" -o "$tmp/out" ;;
            *.ko.xz) xz -c --check=crc32 "$tmp/m.ko" > "$tmp/out" ;;
            *.ko.gz) gzip -9 -c "$tmp/m.ko" > "$tmp/out" ;;
            *.ko) cp "$tmp/m.ko" "$tmp/out" ;;
          esac \
     || [[ ! -s $tmp/out ]]; then
    rm -rf "$tmp"
    return 1
  fi
  sudo install -m 644 "$tmp/out" "$module"
  rm -rf "$tmp"
  sudo depmod -a "$KERNEL"
}

# Returns 0 if the key is enrolled, 2 if it waits for the reboot, 1 if it is not enrolled.
mok_state() {
  local out
  out="$(sudo mokutil --test-key "$MOK_CERT" 2>&1 || true)"
  case "$out" in
    *"already enrolled"*) return 0 ;;
    *"enrollment request"*) return 2 ;;
    *) return 1 ;;
  esac
}

build_v4l2loopback_from_source() {
  local version="$V4L2LOOPBACK_VERSION" tmp src="/usr/src/v4l2loopback-$V4L2LOOPBACK_VERSION"
  if [[ ! -e "/lib/modules/$KERNEL/build" ]]; then
    CAMERA_ERROR="The kernel headers for $KERNEL are missing, so the virtual camera cannot be built.
Update Ubuntu (sudo apt update && sudo apt full-upgrade), reboot into the newest kernel and run this installer again."
    return 1
  fi
  if ! printf '%s\n' "$KERNEL" 6.15 | sort -V -C; then
    CAMERA_ERROR="v4l2loopback $version does not build on kernel $KERNEL (6.15 or newer) and the Ubuntu package did not work either."
    return 1
  fi
  say "Building the official v4l2loopback $version for kernel $KERNEL (takes a minute)..."
  tmp="$(mktemp -d)"
  if ! git clone -q --depth 1 --branch "v$version" https://github.com/umlaeute/v4l2loopback.git "$tmp/src"; then
    rm -rf "$tmp"
    CAMERA_ERROR="Could not download v4l2loopback $version from GitHub."
    return 1
  fi
  if [[ "$(git -C "$tmp/src" rev-parse HEAD)" != "$V4L2LOOPBACK_COMMIT" ]]; then
    rm -rf "$tmp"
    CAMERA_ERROR="The v4l2loopback v$version source does not match the expected commit. Not building it."
    return 1
  fi
  if ! grep -q "^PACKAGE_VERSION=\"\\?$version\"\\?\$" "$tmp/src/dkms.conf"; then
    rm -rf "$tmp"
    CAMERA_ERROR="Unexpected PACKAGE_VERSION in v4l2loopback's dkms.conf. Not building it."
    return 1
  fi
  rm -rf "$tmp/src/.git"
  # Clean up a previous attempt (dkms 2.8 keeps the module "added" even if the build failed).
  sudo dkms remove -m v4l2loopback -v "$version" --all >/dev/null 2>&1 || true
  sudo rm -rf "/var/lib/dkms/v4l2loopback/$version" "$src"
  sudo cp -r "$tmp/src" "$src"
  rm -rf "$tmp"
  if ! sudo dkms install -m v4l2loopback -v "$version" -k "$KERNEL"; then
    CAMERA_ERROR="Building v4l2loopback $version failed. Build log:
/var/lib/dkms/v4l2loopback/$version/build/make.log"
    return 1
  fi
}

# Ubuntu 22.04 ships 0.12.7-2ubuntu2, which does not build on kernel 6.8 or newer
# (strlcpy was removed). Do not even try it there: a failed attempt breaks dpkg.
distro_package_usable() {
  local candidate
  candidate="$(apt-cache policy v4l2loopback-dkms 2>/dev/null | awk '/Candidate:/ {print $2}')"
  [[ -n $candidate && $candidate != "(none)" ]] || return 1
  if ! printf '%s\n' "$KERNEL" 6.8 | sort -V -C \
     && dpkg --compare-versions "$candidate" lt 0.12.7-2ubuntu5; then
    return 1
  fi
}

# v4l2loopback 0.12.7 (the one bundled with the 6.8 HWE kernel package) can leave
# the device without output capabilities, which pyvirtualcam rejects. On kernels
# 6.8+ only trust a DKMS build (updates/) and build 0.13.2 otherwise.
v4l2loopback_usable() {
  local module
  module="$(modinfo -n v4l2loopback 2>/dev/null)" || return 1
  [[ -n $module ]] || return 1
  if printf '%s\n' "$KERNEL" 6.8 | sort -V -C; then
    return 0
  fi
  case "$module" in
    */updates/* | */extra/*) return 0 ;;
  esac
  return 1
}

install_v4l2loopback() {
  if v4l2loopback_usable; then
    return 0
  fi
  # The running kernel may still have the old module loaded.
  RELOAD_MODULE=true
  if distro_package_usable; then
    say "Installing the virtual camera package (v4l2loopback-dkms)..."
    if sudo apt-get install -y v4l2loopback-dkms && v4l2loopback_usable; then
      return 0
    fi
    say "Ubuntu's v4l2loopback package does not build for kernel $KERNEL."
    # Leave dpkg clean so later apt commands (and this installer, next time) keep working.
    sudo dpkg --purge v4l2loopback-dkms \
      || sudo dpkg --purge --force-remove-reinstreq v4l2loopback-dkms || true
  fi
  build_v4l2loopback_from_source
}

load_v4l2loopback() {
  local output
  if [[ ${RELOAD_MODULE:-false} == true && -d /sys/module/v4l2loopback ]]; then
    say "Reloading v4l2loopback with the new module: close OBS or any app using a virtual camera."
    sudo modprobe -r v4l2loopback 2>/dev/null \
      || warn "Warning: could not unload the old v4l2loopback; it will stay loaded until you reboot."
  fi
  [[ -e /sys/devices/virtual/video4linux/video$CAM_NR ]] \
    && [[ "$(cat "/sys/devices/virtual/video4linux/video$CAM_NR/name" 2>/dev/null)" == "$CAM_LABEL" ]] \
    && return 0
  # If it is already loaded with other options, reload it with ours.
  if [[ -d /sys/module/v4l2loopback ]]; then
    say "Reloading v4l2loopback: if OBS or another app is using a virtual camera, close it first."
    sudo modprobe -r v4l2loopback 2>/dev/null || true
  fi
  if ! output="$(sudo modprobe v4l2loopback 2>&1)"; then
    CAMERA_ERROR="Could not load v4l2loopback: $output"
    if [[ $output == *"Key was rejected"* ]]; then
      CAMERA_ERROR+="
Secure Boot rejected the module: its signing key is not enrolled (see 'Troubleshooting' in README.md)."
    fi
    return 1
  fi
  if [[ ! -e /sys/devices/virtual/video4linux/video$CAM_NR ]]; then
    CAMERA_ERROR="v4l2loopback is loaded with other options (another app is using it).
Close OBS or any app using a virtual camera and run: sudo modprobe -r v4l2loopback && sudo modprobe v4l2loopback"
    return 1
  fi
}

setup_camera() {
  local sb=false state=0
  if secure_boot_enabled; then
    sb=true
    ensure_mok_key
  fi
  install_v4l2loopback || return 1

  say "Configuring the virtual camera '$CAM_LABEL' (/dev/video$CAM_NR)..."
  echo "v4l2loopback" | sudo tee /etc/modules-load.d/vanishcam.conf >/dev/null
  echo "options v4l2loopback devices=1 video_nr=$CAM_NR card_label=\"$CAM_LABEL\" exclusive_caps=1" \
    | sudo tee /etc/modprobe.d/vanishcam.conf >/dev/null

  if [[ $sb == true ]]; then
    if ! module_signed; then
      sign_module || warn "Warning: could not sign the module; it will not load with Secure Boot on."
    fi
    mok_state || state=$?
    if [[ $state -eq 1 ]]; then
      if load_v4l2loopback 2>/dev/null; then
        return 0   # Module validation is off, nothing else to do.
      fi
      cat <<'EOF'

[VanishCam] Secure Boot is on, so the virtual camera module has to be signed with a key
            that your computer trusts. Choose a one-time password now (8 to 16 characters);
            you will type it once more after rebooting.
EOF
      if ! sudo mokutil --import "$MOK_CERT"; then
        CAMERA_ERROR="Could not register the Secure Boot key (mokutil --import failed)."
        return 1
      fi
      state=2
    fi
    if [[ $state -eq 2 ]]; then
      CAMERA_STATUS=reboot
      return 0
    fi
  fi
  load_v4l2loopback
}

setup_camera || CAMERA_STATUS=failed

say "Creating the Python environment in .venv..."
# Recreate it if it is broken (folder moved, Python upgraded, interrupted run).
if [[ -x "$VENV_DIR/bin/python" ]] && ! "$VENV_DIR/bin/python" -m pip --version >/dev/null 2>&1; then
  rm -rf "$VENV_DIR"
fi
[[ -x "$VENV_DIR/bin/python" ]] || python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
"$VENV_DIR/bin/python" -m pip install --require-hashes -r "$APP_DIR/requirements.lock.txt"

say "Downloading MediaPipe models..."
"$VENV_DIR/bin/python" -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" "$APP_DIR"

say "Adding VanishCam to the applications menu..."
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
mkdir -p "$ICON_DIR" "$HOME/.local/share/applications"
cp "$APP_DIR/assets/vanish_icon.png" "$ICON_DIR/vanishcam.png"
gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" >/dev/null 2>&1 || true
cat > "$HOME/.local/share/applications/vanishcam.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=VanishCam
Comment=Vanishing effects for your webcam (Zoom, Meet)
Exec="$APP_DIR/vanishcam.sh"
Icon=vanishcam
Terminal=true
Categories=AudioVideo;Video;
EOF

case "$CAMERA_STATUS" in
  ok)
    say "Done. Start it with ./vanishcam.sh (or from the menu: VanishCam)"
    say "In Zoom or Meet choose the camera '$CAM_LABEL'."
    ;;
  reboot)
    cat <<EOF

[VanishCam] Almost done: one reboot is needed to trust the virtual camera (Secure Boot).
  1. Reboot. A blue screen (MOK management) appears before Ubuntu starts.
  2. Choose "Enroll MOK" -> "Continue" -> "Yes", type the password you just chose, then "Reboot".
     (If you miss it, nothing breaks: run this installer again and it asks again.)
  3. After Ubuntu starts, run this installer again: $APP_DIR/install-ubuntu.sh
EOF
    ;;
  failed)
    warn "Python and the models are installed, but the virtual camera is not ready:"
    printf '%s\n' "$CAMERA_ERROR" >&2
    warn "See 'Troubleshooting (Ubuntu)' in README.md, then run this installer again."
    exit 1
    ;;
esac
