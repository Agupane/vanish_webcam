# AGENTS.md

Context for coding agents working on this repo.

## What this is

VanishCam: a local webcam app that makes the person "vanish" with an effect when they make a hand gesture, and sends the
result to a virtual camera for Zoom / Google Meet. Fork of `Nicovic17/vanish_webcam` (remote `upstream`); this fork is
`Agupane/vanish_webcam` (remote `origin`, branch `main`). User-facing docs in Spanish: `README_UBUNTU.md`.

## Layout

| File | What |
|---|---|
| `vanish_cam.py` | Entry point: args, camera/virtual camera, model loading, gesture hold, main loop (state machine) |
| `dragonball_effect.py` | Dragon Ball mode (default): Instant Transmission pose (two fingers on forehead), teleport render, generated sound |
| `naruto_effect.py` | Naruto mode: joined palms, smoke + falling log, reverse effect to reappear |
| `super_saiyan_effect.py` | Super Saiyan (inside Dragon Ball): charge-ki pose, `PowerState`, `AuraRenderer`, golden hair (`HairTracker`), synthesized sounds |
| `vanish_sound.py` | Plays an effect sound (pygame, or `ffplay` fallback); `play(loops, fade_ms)`, `stop(fade_ms)`, `set_volume` |
| `test_*.py` | unittest suite; `run_loop()` in `test_video_output.py` drives the real loop with a fake clock |
| `install-ubuntu.sh`, `vanishcam.sh` | Ubuntu installer (v4l2loopback + venv + models) and launcher |
| `*.bat`, `VanishCam.spec`, `BUILD_WINDOWS.bat` | Upstream Windows launchers/build; still expect a `local_app/` folder and are not maintained here |
| `run3.py` | Unrelated upstream meme tracker; missing its `memes/` assets. Ignore it |
| `hand_landmarker.task`, `face_landmarker.task` | MediaPipe models shipped in the repo |
| `models/` (gitignored) | Downloaded at runtime: selfie segmenter, gesture recognizer, multiclass segmenter (hair; optional), generated `teleport.wav` and `ssj_*.wav` |

## How the loop works

Phases (`AppState.phase`): `calibrating` → `ready` → `vanishing` → `vanished` → `appearing` → `ready`.

- **Calibrating:** 4 s; the background is the median of the frames from the last 1.5 s (every other frame, max 24).
  If the segmenter sees a person while sampling, the sampling window is pushed back 2 s, up to 3 times.
- **Gestures:** checked in `ready` and `vanished`. `GestureHold` requires the pose to be held (Dragon Ball 1 s,
  others 0.3 s, 0.25 s grace for a missed frame) and to be released before it can trigger again. The same gesture
  vanishes and brings the person back.
- **While vanished:** the output is a frozen frame (background, plus the log in Naruto mode).
- **Super Saiyan (Dragon Ball only):** a second state machine (`ssj.PowerState`: `off` → `charging` → `flash` →
  `super` → `powering_down`) that runs only in `ready`. The charge pose (two fists at chest height, one on each side
  of the nose) is read from the same Hand/Face Landmarker result as the teleport (`power_active`; the teleport wins),
  held 1.5 s with its own `GestureHold`. Hair: `selfie_multiclass_256x256` in IMAGE mode on a head crop at 10 Hz
  (`hair_mask`); without it only the aura is drawn. Teleporting while transformed keeps the golden hair and pauses
  the hum.
- **Keys** (OpenCV window must have focus): `V` vanish, `R` reappear, `S` Super Saiyan on/off (Dragon Ball), `SPACE` recalibrate, `F` fullscreen, `Q`/`ESC` quit.
- **Mirroring:** the preview is mirrored; the virtual camera gets the unmirrored image unless `--mirror-output`.

## Rules

- Never draw text or UI on the video (preview or virtual camera); tests patch `cv2.putText` to fail. Messages go to the terminal.
- Terminal messages and docs are in Spanish (rioplatense). Code comments are a mix of Italian (upstream) and English; keep whichever the surrounding code uses.
- Do not add copyrighted anime audio or frames. The teleport sound is synthesized in `write_teleport_sound`; a user may drop their own `assets/teleport.MP3`, which takes precedence.
- MediaPipe VIDEO-mode tasks need strictly increasing timestamps: run each task at most once per frame.
- Keep the loop testable: patchable seams are `gesture_active`, `person_mask`, `person_in_frame`, `create_tasks`,
  `open_camera`, `open_virtual_camera`, `VanishSound`, `teleport_sound_path`, `power_active`, `hair_mask`,
  `create_hair_tracker` and `ssj_sound_paths`.
- Super Saiyan sounds are synthesized too (`write_charge_sound`, `write_transform_sound`, `write_aura_hum`);
  `assets/ssj_charge.MP3`, `assets/ssj_transform.MP3` and `assets/ssj_aura.MP3` override them.

## Tests

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -p 'test_*.py'
```

On a headless Linux box MediaPipe needs `libegl1` (`sudo apt install libegl1`), otherwise the tests that create
`mp.Image` fail with `libEGL.so.1` errors.

## Platforms

- **Ubuntu:** supported (`install-ubuntu.sh`, virtual camera via v4l2loopback).
- **Windows / macOS:** the Python code runs (virtual camera through OBS), but there is no easy installer yet.
  MediaPipe 1.x has no wheel for Intel Macs.
