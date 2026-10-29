# Security policy

## Reporting a vulnerability

Please report vulnerabilities **privately** through GitHub's
[private vulnerability reporting](https://github.com/Agupane/vanish_webcam/security/advisories/new) (repository
**Security** tab → **Report a vulnerability**). Don't open a public issue for security problems. Include what you
found, how to reproduce it and which platform and install method you used. We'll acknowledge the report and keep you
updated while it is fixed.

Only the latest `main` branch is supported; there are no versioned releases yet.

## Security properties

What VanishCam is designed to guarantee (a report that breaks any of these is a vulnerability):

- **Local-only processing.** Video is processed on your computer. VanishCam does not save frames to disk and opens no
  network connections except the first download of the Google MediaPipe models.
- **Verified models.** Downloaded models are checked against SHA-256 hashes (`MODEL_SHA256` in `vanish_cam.py`) and
  discarded if they don't match.
- **Pinned kernel module source.** When `install-ubuntu.sh` has to build v4l2loopback, it checks out a fixed release
  and verifies its exact commit (`V4L2LOOPBACK_COMMIT`) before building, because that code runs in the kernel.
- **No elevated app.** The app itself runs as your user; only the Linux installer uses `sudo` (packages, kernel
  module, Secure Boot key enrollment) and the Windows installer may ask for administrator rights to install OBS.

## Caveat: one-line installers

`curl ... | bash` and `irm ... | iex` run whatever is on this repository's `main` branch at that moment, without a
chance to review it. If you prefer, clone the repository, read `install.sh`, `install-ubuntu.sh` or `install.ps1`, and
run them by hand. Dependencies are installed from PyPI with version ranges (see `requirements.txt`), not hash-pinned.
