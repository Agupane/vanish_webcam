#!/usr/bin/env bash
# Updates an existing VanishCam install in place: code, Python dependencies and models.
# Keeps .venv, models/ and the system integration (virtual camera) untouched.
# Usage: ./update.sh            (Linux/macOS; on Windows run install.ps1 again)
#        VANISHCAM_REF=v1.0.0 ./update.sh
set -euo pipefail

REPO="Agupane/vanish_webcam"
REF="${VANISHCAM_REF:-main}"
APP_DIR="${VANISHCAM_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)}"

say() { printf '\n[VanishCam] %s\n' "$*"; }
fail() { printf '\n[VanishCam] %s\n' "$*" >&2; exit 1; }

if [[ ${1:-} != --apply ]]; then
  [[ -f "$APP_DIR/vanish_cam.py" ]] || fail "Run this from the VanishCam folder."
  [[ -x "$APP_DIR/.venv/bin/python" ]] || fail "VanishCam is not installed yet: run ./install.sh first."
  tmp="$(mktemp -d)"
  say "Downloading VanishCam ($REF)..."
  if ! curl -fsSL "https://github.com/$REPO/archive/$REF.tar.gz" -o "$tmp/src.tar.gz"; then
    rm -rf "$tmp"
    fail "Could not download $REPO ($REF)."
  fi
  mkdir -p "$tmp/src"
  if ! tar -xzf "$tmp/src.tar.gz" -C "$tmp/src" --strip-components=1; then
    rm -rf "$tmp"
    fail "The downloaded archive is not valid."
  fi
  # Run the downloaded copy: replacing this file while bash reads it can corrupt the run.
  exec env VANISHCAM_APP_DIR="$APP_DIR" VANISHCAM_TMP="$tmp" \
    bash "$tmp/src/update.sh" --apply "$tmp/src"
fi

src="${2:?missing source folder}"
[[ -n "${VANISHCAM_TMP:-}" ]] && trap 'rm -rf "$VANISHCAM_TMP"' EXIT

say "Updating the code in $APP_DIR..."
cp -R "$src"/. "$APP_DIR"/
chmod +x "$APP_DIR"/*.sh

say "Updating the Python dependencies..."
python="$APP_DIR/.venv/bin/python"
if [[ ! -x $python ]]; then
  fail "The Python environment is missing: run ./install.sh first."
fi
if command -v uv >/dev/null; then
  uv pip install --python "$python" --require-hashes -r "$APP_DIR/requirements.lock.txt"
else
  "$python" -m pip install --require-hashes -r "$APP_DIR/requirements.lock.txt"
fi

say "Checking the MediaPipe models..."
"$python" -c "import sys; sys.path.insert(0, sys.argv[1]); import vanish_cam; vanish_cam.download_models('normal')" "$APP_DIR"

say "Done. Start it with ./vanishcam.sh"
