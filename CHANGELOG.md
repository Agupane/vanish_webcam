# Changelog

All notable changes to this fork are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no versioned releases yet.

## [Unreleased]

### Added

- `LICENSE` (MIT, for this fork's contributions), `NOTICE.md` (upstream code and third-party licenses),
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`, `.editorconfig`, issue and pull
  request templates, and an "About this fork" section in the README.
- Super Saiyan transformation inside Dragon Ball mode: hold the charge-ki pose for 1.5 s to get an aura and golden
  hair (multiclass hair segmentation), with synthesized charge, transform and aura sounds; `S` toggles it (`763da74`).
- Installers for Windows (`install.ps1` with uv and OBS via winget), macOS (`install.sh` with uv and OBS) and Linux,
  launchers `vanishcam.sh` / `vanishcam.bat`, and CI that runs the tests and `--self-test` on Ubuntu, Windows, macOS
  arm64 and macOS Intel (`144ceb7`).
- `--call-audio` on Linux: a PulseAudio/PipeWire virtual microphone (VanishCam-Mic) that mixes the real microphone
  with the effect sounds (`144ceb7`).
- `--audio-device NAME` sends the effect sounds to a specific output device (VB-Cable on Windows, BlackHole on macOS),
  so a call can pick them up; documented in the README and the guide.
- `uninstall-ubuntu.sh` undoes the Ubuntu integration (virtual camera config, DKMS build, menu entry) without touching
  the app folder or the shared Secure Boot key.
- `update.sh` updates an existing install in place (code, dependencies and models) and keeps `.venv`, `models/` and
  the virtual camera config.
- `--list-cameras` and a camera picker window with a live preview when several webcams are found: the preview no
  longer silently uses a disabled laptop camera instead of a USB one (change with `A`/`D` or arrows, `Enter` to start,
  `Q` to cancel).
- `requirements.lock.txt`: pinned dependencies with hashes, installed with `--require-hashes` by every installer and by
  CI. The installers also verify the SHA-256 of the pinned uv installer and accept `VANISHCAM_REF` to install a tag or
  commit instead of `main`.
- Experimental macOS `.app` build (`VanishCam.macos.spec`, `BUILD_MACOS.sh`); the Windows PyInstaller spec now bundles
  the face model, the Super Saiyan model and the new modules.
- Dragon Ball mode, now the default: Instant Transmission pose (two fingers on the forehead, held 1 s) with speed lines,
  a flash and a synthesized teleport sound (`686a50b`).
- Ubuntu support: the virtual camera goes through v4l2loopback (device named VanishCam) for Zoom and Google Meet,
  with `install-ubuntu.sh` and `vanishcam.sh` (`e74cb0b`).
- `GUIDE.md` usage guide and `AGENTS.md` context for contributors and coding agents.

### Changed

- Gestures must be held and released before they trigger again, and the same gesture vanishes and brings the person
  back, with reappear effects (`686a50b`).
- Better background capture: the background is the median of the last frames of calibration, and sampling is pushed
  back while a person is in the frame (`686a50b`).
- The virtual camera gets the unmirrored image (the preview stays mirrored) unless `--mirror-output` (`686a50b`).
- The whole repository (UI messages, docs, comments, tests) is in English; the upstream README is kept as
  `README_ORIGINAL.md` and the upstream `AVVIA_*.bat` launchers delegate to `vanishcam.bat` (`dcc9c90`, `144ceb7`).
- `requirements.txt` pins version ranges, with MediaPipe 0.10.14 / numpy < 2 / OpenCV 4.10 on Intel Macs (`144ceb7`).

### Fixed

- `install-ubuntu.sh` recovers from a broken `v4l2loopback-dkms` package (Ubuntu 22.04 with 6.8+ kernels) by
  building upstream v4l2loopback 0.13.2 with DKMS, and handles Secure Boot module signing / MOK enrollment
  (`89a44cf`, `11c4d3f`).
- `install-ubuntu.sh` no longer accepts the 0.12.7 module bundled with the 6.8 HWE kernel on kernels 6.8 or newer:
  it builds 0.13.2 and reloads it, so the virtual camera advertises `VIDEO_OUTPUT` (pyvirtualcam rejected the
  kernel-provided module with "is not a video output device"). `vanishcam.sh` warns when the device is in that state.
- CI failures on Windows and Ubuntu (`66136fc`).
- macOS arm64: MediaPipe 1.0.1 aborted in its Metal helper during `--self-test`. `requirements.txt` now pins MediaPipe
  1.2.0 on every platform except Intel Macs, which keep 0.10.14 (no 1.x x86_64 wheels); the whole CI matrix is green.
  Upstream PR Nicovic17/vanish_webcam#2 reports and fixes the same crash with 1.1.1.

### Security

- Downloaded MediaPipe models are verified against SHA-256 hashes before use (`144ceb7`).
- The v4l2loopback source built by the installer is pinned to the commit of its release tag (`144ceb7`).
- The MediaPipe model URLs are now versioned (`/1/` instead of `/latest/`), so a new upstream version cannot silently
  change what is downloaded. The uv installer is downloaded from a versioned release URL and checked against a pinned
  SHA-256 before it runs, and dependencies come from a hashed lock file.

## Upstream baseline - 2026-10-24

This fork starts from [Nicovic17/vanish_webcam](https://github.com/Nicovic17/vanish_webcam) at commit `1e008cf`
(upstream history `f0f4372`..`1e008cf`, 9 to 24 October 2026): the local webcam vanish app with Normal and Naruto
modes, a Windows-oriented launcher set (`AVVIA_*.bat`) and a PyInstaller build (`VanishCam.spec`,
`BUILD_WINDOWS.bat`). The unrelated `run3.py` meme tracker was dropped from this fork. Upstream code is not covered by
this fork's license; see [NOTICE.md](NOTICE.md).

[Unreleased]: https://github.com/Agupane/vanish_webcam/compare/1e008cf...main
