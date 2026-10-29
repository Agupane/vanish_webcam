# Changelog

All notable changes to this fork are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). The project has no versioned releases yet.

## [Unreleased]

### Changed

- Super Saiyan silhouette after real-call tests (owner, Windows, Meet): above the eyes only the head counts as the
  person, so a high-back chair behind the head is left out; below the eyes the segmenter mask is kept as it is. The
  previous cut by color difference with the background photo failed in a dark room and with a swivel chair, and made
  holes where a black hoodie sat in front of the black chair, so the aura painted blocky patches on the body. The aura
  also surrounds the golden hair, so the flames rise from the spikes, and the golden eyebrows are softer (they read as
  painted bars).

- Started without options (Desktop shortcut, Applications menu), VanishCam opens a home window (`home_ui.py`) for the
  effect, the camera and the Super Saiyan hair (take photos, copy the prompt, open the folder, check the pictures),
  then **START**. It remembers the last effect and camera (by name) in the gitignored `vanishcam_settings.json`.
  `--home` shows it with other options; any option skips it as before.
- Windows camera picker: webcams are listed by name (`pygrabber`, DirectShow order = OpenCV index), virtual cameras
  (OBS Virtual Camera, Meta Quest headsets...) are hidden, the only real webcam is opened directly instead of index 0,
  and `--list-cameras` works on Windows. With only virtual cameras VanishCam stops with a list instead of reading one.

- Super Saiyan aura, second version: three flat cel-shaded tones with rising flame tongues, alpha blended so it shows on
  light walls; the room darkens while transformed and a thin rim of light runs inside the edge of the body (the
  interior is untouched). The calibrated background photo plus a head ellipse from the face landmarks remove static
  furniture (a high-back chair) from the silhouette. The aura is no longer cut by a straight line at the sides, and its
  geometry is cached per mask update (~4–5 ms per frame at 960×540 on claude-bcn, down from ~6 ms). The README, the
  guide and the status panel tell users to turn off background blur in their call app.

### Added

- Super Saiyan face: teal irises and golden eyebrows while transformed (face landmarks; whites, lids and skin
  untouched), and the user's own golden hair. `--ssj-hair-photos` takes guided photos (front and both sides) into the
  gitignored `ssj_hair/` folder and prints a prompt; the user turns them into Super Saiyan pictures with ChatGPT,
  Gemini or any image tool and saves them as `ssj_hair/ssj_*.png`. At startup the golden hair is cut out (Lab color
  test, face landmarks), cached in `ssj_hair/.cache/`, and fitted on the live face with a similarity transform, picking
  the picture closest to the head turn. The hair and eyes flicker in late in the charge. VanishCam itself still opens
  no network connections (`ssj_face.py`).
- `LICENSE` (MIT, for this fork's contributions), `NOTICE.md` (upstream code and third-party licenses),
  `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` (Contributor Covenant 2.1), `SECURITY.md`, `.editorconfig`, issue and pull
  request templates, and an "About this fork" section in the README.
- Super Saiyan transformation inside Dragon Ball mode: hold the charge-ki pose for 1.5 s to get an aura and golden
  hair (multiclass hair segmentation; later replaced by the procedural aura), with synthesized charge, transform and
  aura sounds; `S` toggles it (`763da74`).
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
- Dragon Ball now uses `assets/teleport.mp3`, copied from the `bernardocm10/vanish_webcam` fork at the owner's
  request (not MIT; see NOTICE.md). Custom sounds are found whatever the extension case (`.MP3`, `.mp3`, `.wav`,
  `.ogg`, `.m4a`, `.flac`).
- A side status panel next to the preview shows the next step, the keys and the recent events, so the terminal is
  optional. The Qt toolbar with its unreadable buttons and tooltips is hidden.
- Super Saiyan: the charge pose accepts both fists in front of the face (forehead to chin), not only at chest
  height. The last good face is reused for a moment when the fists hide it, so the pose survives the occlusion.
- Super Saiyan: the effect is now a procedural aura that surrounds the silhouette and never paints the hair or body.
  The earlier `saiyanaura.gif` + golden-hair/spiky-crest pipeline was removed because it looked wrong. The aura runs
  at half resolution, the person mask updates at 10 Hz during the transformation, and `render_super_saiyan` stays
  under the live-video budget.
- Performance pass: the person mask is blurred at model resolution, `cv2.boundingRect` replaces `findNonZero` in the
  hot paths, the side panel is cached by content and calibration reuses one mask for the person check and the setup
  outline.
- Guided setup while the background is captured: the preview outlines the detected person, the panel says whether to
  step out, `P` pauses/resumes and `R` restarts the setup.
- Super Saiyan uses the owner-supplied `assets/ssj_transform.mp3` (not MIT; see NOTICE.md). The aura is generated
  procedurally, so no image asset is needed.
- Ubuntu installs the app icon (`assets/vanish_icon.png`) and uses it for the Applications menu entry instead of the
  generic camera icon.
- `requirements.lock.txt`: pinned dependencies with hashes, installed with `--require-hashes` by every installer and by
  CI. The installers also verify the SHA-256 of the pinned uv installer and accept `VANISHCAM_REF` to install a tag or
  commit instead of `main`.
- Experimental macOS `.app` build (`VanishCam.macos.spec`, `BUILD_MACOS.sh`); the Windows PyInstaller spec now bundles
  the face model and the new modules.
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
