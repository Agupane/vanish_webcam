#!/usr/bin/env bash
# Builds dist/VanishCam.app on macOS. Experimental: it has not been tested on a Mac yet.
# Needs Python 3.12 (python3.12) and an internet connection for the models.
# The app still needs OBS Studio 30 or later for its virtual camera.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python3.12}"
if ! command -v "$PYTHON" >/dev/null; then
  echo "[VanishCam] $PYTHON not found. Install it (brew install python@3.12) or set PYTHON=..." >&2
  exit 1
fi

BUILD_VENV=.venv-build
"$PYTHON" -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/python" -m pip install --upgrade pip
"$BUILD_VENV/bin/python" -m pip install --require-hashes -r requirements.lock.txt
"$BUILD_VENV/bin/python" -m pip install "pyinstaller>=6,<7"

"$BUILD_VENV/bin/python" -c "from vanish_cam import download_models; download_models()"
"$BUILD_VENV/bin/python" -m PyInstaller --noconfirm --distpath dist --workpath build VanishCam.macos.spec

"dist/VanishCam.app/Contents/MacOS/VanishCam" --self-test
echo
echo "[VanishCam] Done: dist/VanishCam.app"
