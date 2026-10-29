# AGENTS.md

Context for coding agents working on this repo.

## What this is

VanishCam: a local webcam app that makes the person "vanish" with an effect when they make a hand gesture, and sends the
result to a virtual camera for Zoom / Google Meet. Fork of `Nicovic17/vanish_webcam` (remote `upstream`); this fork is
`Agupane/vanish_webcam` (remote `origin`, branch `main`). User-facing docs: `README.md` (install) and `GUIDE.md` (usage guide).
Algorithm inventory, measured costs, hot spots and the optimization backlog: [ALGORITHMS.md](ALGORITHMS.md).

## Layout

| File | What |
|---|---|
| `vanish_cam.py` | Entry point: args, camera/virtual camera, model loading, gesture hold, main loop (state machine) |
| `dragonball_effect.py` | Dragon Ball mode (default): Instant Transmission pose (two fingers on forehead), teleport render, generated sound |
| `naruto_effect.py` | Naruto mode: joined palms, smoke + falling log, reverse effect to reappear |
| `super_saiyan_effect.py` | Super Saiyan (inside Dragon Ball): charge-ki pose, `PowerState`, procedural `AuraRenderer` (surrounds the silhouette, never paints the person), synthesized sounds |
| `home_ui.py` | Home window (OpenCV-drawn): effect, camera, Super Saiyan hair actions, START; `run_home(settings, actions)` with callbacks from `vanish_cam`; settings file and clipboard/folder helpers |
| `vanish_sound.py` | Plays an effect sound (pygame, or `ffplay` fallback); `play(loops, fade_ms)`, `stop(fade_ms)`, `set_volume` |
| `ssj_face.py` | Super Saiyan face: teal irises, golden brows, import of the user's golden hair pictures (`ssj_hair/ssj_*.png`) and `HairOverlay`, which fits the hair on the live face |
| `tools/aura_preview.py` | Renders the Super Saiyan aura on a synthetic scene (light/dark wall, chair) for tuning without a camera |
| `test_*.py` | unittest suite; `run_loop()` in `test_video_output.py` drives the real loop with a fake clock |
| `install.sh` | Installer for macOS (uv + OBS) and Linux (delegates to `install-ubuntu.sh`); works via `curl \| bash` |
| `install-ubuntu.sh` | apt packages, v4l2loopback (falls back to building a pinned upstream commit with DKMS), venv, models, `.desktop` |
| `uninstall-ubuntu.sh` | Undoes the Ubuntu integration (module config, DKMS build, menu entry); keeps the app folder and the MOK key |
| `update.sh` | Updates an existing install in place (code, dependencies, models); keeps `.venv`, `models/` and the camera setup |
| `requirements.txt` / `requirements.lock.txt` | Human-edited ranges / uv-generated lock with hashes, used by the installers and CI |
| `install.ps1`, `vanishcam.bat` | Windows installer (uv + winget OBS + desktop shortcut) and launcher |
| `vanishcam.sh` | Launcher for Linux (v4l2loopback device named VanishCam; `--call-audio` builds a PulseAudio/PipeWire virtual mic) and macOS (OBS) |
| `AVVIA_*.bat` | Upstream launcher names, now delegating to `vanishcam.bat` |
| `VanishCam.spec`, `BUILD_WINDOWS.bat` | Upstream PyInstaller build, updated for the fork's files; untested |
| `VanishCam.macos.spec`, `BUILD_MACOS.sh` | Experimental macOS `.app` build; never run on a Mac |
| `README_ORIGINAL.md` | Upstream README (English), kept for reference |
| `LICENSE`, `NOTICE.md` | MIT for this fork's contributions; NOTICE lists upstream (unlicensed) files and third-party licenses |
| `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, `CHANGELOG.md`, `.github/` | Contributor docs, templates and CI |
| `hand_landmarker.task`, `face_landmarker.task` | MediaPipe models shipped in the repo |
| `models/` (gitignored) | Downloaded at runtime: selfie segmenter, gesture recognizer, generated `teleport.wav` and `ssj_*.wav` |
| `ALGORITHMS.md` | Algorithm map for agents: what runs, where, measured cost and what to optimize next |

## How the loop works

Phases (`AppState.phase`): `calibrating` → `ready` → `vanishing` → `vanished` → `appearing` → `ready`.

- **Calibrating:** 4 s; the background is the median of the frames from the last 1.5 s (every other frame, max 24).
  If the segmenter sees a person while sampling, the sampling window is pushed back 2 s, up to 3 times.
- **Gestures:** checked in `ready` and `vanished`. `GestureHold` requires the pose to be held (Dragon Ball 1 s,
  others 0.3 s, 0.25 s grace for a missed frame) and to be released before it can trigger again. The same gesture
  vanishes and brings the person back.
- **While vanished:** the output is a frozen frame (background, plus the log in Naruto mode).
- **Super Saiyan (Dragon Ball only):** a second state machine (`ssj.PowerState`: `off` → `charging` → `flash` →
  `super` → `powering_down`) that runs only in `ready`. The charge pose (two clenched fists in front of the face, one on each side
  of the nose) is read from the same Hand/Face Landmarker result as the teleport (`power_active`; the teleport wins),
  held 1.5 s with its own `GestureHold`. The effect is a procedural `AuraRenderer` around the person silhouette
  (distance transform + rising flames + sparks, half resolution, masked out inside the person): it never recolors the
  hair or paints the body. Teleporting while transformed keeps the transformation state and pauses/resumes the hum.
- **Home window:** the launchers pass `--home` when started without options; `run()` shows `home_ui.run_home` and
  then `run_camera` with the chosen mode and camera. Actions are callbacks (`home_actions`), so `home_ui` has no
  webcam or MediaPipe code. The camera is remembered by name in `vanishcam_settings.json` (gitignored).
- **Cameras:** `find_cameras` returns `[(source, label)]`: Linux from sysfs (v4l2loopback skipped), Windows from
  `pygrabber` in DirectShow order (= OpenCV index with `CAP_DSHOW`), hiding names in `VIRTUAL_CAMERA_WORDS` (OBS
  Virtual Camera is a DirectShow camera too: never read our own output); macOS has no picker yet.
- **Keys** (OpenCV window must have focus): `V` vanish, `R` reappear (restart setup while calibrating), `S` Super Saiyan on/off (Dragon Ball), `SPACE` recalibrate, `P` pause/resume, `F` fullscreen, `Q`/`ESC` quit.
- **Guided setup:** during calibration the preview outlines the detected person (`draw_setup_marks`, HUD only) and the side panel says whether to step out; `P` freezes the loop and `R` restarts calibration.
- **Mirroring:** the preview is mirrored; the virtual camera gets the unmirrored image unless `--mirror-output`.
- **Status panel:** `render_status_panel` + `compose_dashboard` add a side panel with the next step, keys and recent
  events; `--no-hud` shows the video alone. The virtual camera only ever receives the clean `display` frame.
- **Audio:** `--audio-device NAME` is passed to `pygame.mixer.init(devicename=...)` for the effect sounds (ignored by the `ffplay` fallback and when another sound already owns the mixer, which is the normal case: the first sound initializes it with the device).

## Rules

- Never draw text or UI on the video (preview or virtual camera); tests patch `cv2.putText` to fail. Messages go to the terminal.
- Everything is in English: terminal messages, docs, code comments, docstrings and tests.
- Do not add more copyrighted anime audio or frames. The owner-supplied exceptions, all **not MIT**, are
  `assets/teleport.mp3` (from `bernardocm10/vanish_webcam`) and `assets/ssj_transform.mp3`; everything else is
  synthesized. Users may drop their own `assets/teleport.*` and `assets/ssj_*.{MP3,mp3,wav,ogg,m4a,flac}`, which take
  precedence.
- MediaPipe VIDEO-mode tasks need strictly increasing timestamps: run each task at most once per frame.
- Keep the loop testable: patchable seams are `gesture_active`, `person_mask`, `person_in_frame`, `create_tasks`,
  `open_camera`, `open_virtual_camera`, `VanishSound`, `teleport_sound_path`, `power_active`, `ssj_sound_paths`,
  `load_hair`, `detect_face_points`, `draw_setup_marks`, `render_status_panel`, `compose_dashboard`, `windows_camera_names`, `find_cameras` and
  `take_hair_photos` (closes only its own window: the home window may be open).
- The Super Saiyan hair is never generated or downloaded by VanishCam: the user makes it with an image tool of their
  choice from photos taken with `--ssj-hair-photos` (owner decision, 2026-10-29). Do not add calls to image APIs.
- Super Saiyan sounds are synthesized too (`write_charge_sound`, `write_transform_sound`, `write_aura_hum`);
  `assets/ssj_charge.*`, `assets/ssj_transform.*` and `assets/ssj_aura.*` override them.

## License

- New files and changes in this fork are MIT ([LICENSE](LICENSE)). Upstream (`Nicovic17/vanish_webcam`) has no
  license, so its code and assets are not MIT: don't relicense them or copy them into new files.
- Do not copy code or assets from sources without a license, or with one incompatible with MIT.
- Keep [NOTICE.md](NOTICE.md) in sync: list any new model, asset, dependency or upstream-derived file there, and
  add user-visible changes to [CHANGELOG.md](CHANGELOG.md) under *Unreleased*.

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -p 'test_*.py'
```

For performance work, read [ALGORITHMS.md](ALGORITHMS.md) first; it lists the measured hot spots and the benchmark
recipes.

After editing `requirements.txt`, regenerate the lock the installers and CI use:
`uv pip compile requirements.txt --universal --generate-hashes -o requirements.lock.txt`.

On a headless Linux box MediaPipe needs `libegl1` (`sudo apt install libegl1`), otherwise the tests that create
`mp.Image` fail with `libEGL.so.1` errors.

## Platforms

- **Ubuntu:** `install.sh` → `install-ubuntu.sh`, virtual camera via v4l2loopback.
- **Windows:** `install.ps1`, virtual camera via OBS (pyvirtualcam backend `obs`).
- **macOS:** `install.sh`, virtual camera via OBS 30+ (the user must start/stop OBS's virtual camera once to install
  the system extension). `requirements.txt` pins MediaPipe 1.2.0 for Apple silicon and other platforms, but 0.10.14
  for Intel Macs (1.x has no x86_64 wheels), with numpy < 2 and OpenCV 4.10 via environment markers (untested).
  MediaPipe 1.0.1 aborts on arm64 (`DrishtiMetalHelper`), so do not downgrade below 1.1.
- `.github/workflows/tests.yml` runs the unit tests and `--self-test` on all of them.

## Security

- Downloaded models are checked against `MODEL_SHA256` before use; add the hash when adding a model.
- The v4l2loopback source built by `install-ubuntu.sh` is pinned to a commit (`V4L2LOOPBACK_COMMIT`).
- Never write frames to disk or open network connections other than the model downloads. The only exceptions are the
  photos the user takes on purpose with `--ssj-hair-photos` and the hair cut-outs cached in `ssj_hair/.cache/`;
  `ssj_hair/` is gitignored.
