# Algorithms and performance map

This document is for coding agents (and humans) who need to review, profile or optimize VanishCam without
reverse-engineering the whole loop first. It lists every algorithm that runs in the main path, where it lives, what it
costs, what is already optimized and what is still worth trying.

Keep it in sync when you move a hot function or change an algorithm. Use symbols (`module.function`) rather than exact
line numbers: they survive refactors better.

Last updated: 2026-10-29, after removing the GIF aura and the golden-hair pipeline.

## Current status

| Area | State |
|---|---|
| Main loop, phases, HUD, camera picker | Implemented and covered by unit tests |
| Dragon Ball teleport (pose + effect) | Implemented; verified with a real webcam on Ubuntu, pose tuning still owner-dependent |
| Super Saiyan (pose, power state, procedural aura) | Implemented; the aura is being visually tuned, the real pose needs owner testing |
| Golden hair / GIF aura | **Removed**: they painted the person and looked wrong. The aura is procedural and surrounds the silhouette |
| Normal and Naruto modes | Implemented, not re-verified on hardware after the latest refactors |
| Virtual camera (v4l2loopback) | Verified on the owner's Ubuntu machine (`/dev/video10`, `pyvirtualcam`) |
| Audio, model downloads, installers | Implemented; Windows/macOS hardware paths are still unverified |
| Unit tests | 97 (`python -m unittest discover -p 'test_*.py'`) |

## Frame pipeline

Every captured frame goes through this order. Anything skipped for the current phase is marked.

1. `capture.read()` (blocking, camera FPS) → optional `cv2.flip` for the preview (`--no-mirror` disables it).
2. Open/reuse the virtual camera once (`open_virtual_camera`).
3. Compute `now`, `elapsed_ms` and build the RGB `mp.Image` lazily (`frame_image`) only if a MediaPipe task needs it.
4. **Calibrating:** countdown; sample every other frame during the last 1.5 s (max 24); every 0.3 s check the person
   mask; at 4 s compute the median background. HUD-only: `draw_setup_marks` outlines the person.
5. **Ready / vanished:** every `gesture_interval` run the mode gesture. Dragon Ball and Naruto use 0.08 s (12.5 Hz),
   Normal uses 0.14 s (7.1 Hz). Feed the result to `GestureHold`.
6. **Super Saiyan (Dragon Ball, ready):** `power_active` reads the same Hand/Face Landmarker result as the teleport
   (teleport wins), feeds `power_hold` (1.5 s) and the `PowerState` machine.
7. **Effects:** compute the person mask at 5–20 Hz depending on the effect; render teleport / dissolve / Naruto.
8. **Super Saiyan render:** if the power state is not `off`, update the person mask at 10 Hz and call
   `ssj.render_super_saiyan` (procedural aura + flash + shake).
9. Compose the HUD panel (cached) and `cv2.imshow`; send the clean `display` frame to the virtual camera.
10. `cv2.waitKey(1)`, key handling, `virtual_camera.sleep_until_next_frame()`.

The virtual camera only ever receives `display`; the HUD and the setup outline are preview-only.

## Algorithm inventory

| # | Algorithm | Where | Cost (owner's CPU) | Notes / status |
|---|---|---|---|---|
| 1 | Camera capture (V4L2/MJPG on Linux, AVFoundation on macOS, MSMF/DShow on Windows) | `vanish_cam.open_camera`, `_open_capture` | camera-bound | `--camera N` = `/dev/videoN` on Linux; virtual devices are filtered out |
| 2 | Virtual camera output | `vanish_cam.open_virtual_camera`, `send_virtual_frame` | small | pyvirtualcam BGR; no flip to the call unless `--mirror-output` |
| 3 | Dragon Ball pose (two fingers on forehead) | `dragonball_effect.instant_transmission`, `InstantTransmissionDetector` | ~30 ms per hand+face check | MediaPipe HandLandmarker + FaceLandmarker, VIDEO mode, CPU delegate |
| 4 | Super Saiyan pose (both fists in front of the face) | `super_saiyan_effect.charge_pose`, `hand_tension`, `vanish_cam.power_active` | included in #3 | Reuses the latest hand/face result; a recent face is kept 0.6 s when fists hide it |
| 5 | Normal pose (V sign) | `vanish_cam.victory_landmark_score`, `classify_gesture_result`, `MultiViewGestureRecognizer` | ~10–30 ms per check | Rotations/crops retry only on failure; 0.14 s interval |
| 6 | Naruto pose (joined palms) | `naruto_effect.joined_hands_from_landmarks`, `MultiViewHandLandmarker` | ~10–30 ms per check | Two hands, multi-view retry |
| 7 | Gesture hold / toggle | `vanish_cam.GestureHold` | negligible | 1 s Dragon Ball, 0.3 s others, 0.25 s grace; must release before re-trigger |
| 8 | Person segmentation | `vanish_cam.person_mask` | ~6 ms inference + post | MediaPipe selfie segmenter, VIDEO mode; blur at model resolution, then one resize |
| 9 | Background capture | `vanish_cam.run_camera` calibrating block | median once | 1.5 s of every other frame, max 24; retries 2 s up to 3 times if a person is seen |
| 10 | Dragon Ball teleport render | `dragonball_effect.render_teleport`, `speed_lines`, `person_alpha` | few ms | ROI-based float blend; comic lines only inside the silhouette |
| 11 | Normal dissolve | `vanish_cam.apply_dissolve`, `make_dissolve_fields` | few–10 ms | Full-frame float blend; fields precomputed once |
| 12 | Naruto substitution | `naruto_effect.render_substitution`, `_smoke_layer`, `overlay_log` | few ms | Smoke on a cropped RGBA layer; log sprite cached per scale |
| 13 | Super Saiyan power state | `super_saiyan_effect.PowerState` | negligible | `off → charging → flash → super → powering_down` |
| 14 | Super Saiyan aura | `super_saiyan_effect.AuraRenderer.render`, `refine_person_mask`, `head_ellipse` | ~5.5 ms at 960×540 (claude-bcn; was ~5.9 ms there, ~11 ms on the owner's CPU) | Geometry (refined mask, distance transforms, rim, contour) cached per mask update; per frame: darken, noise, cel-tone LUT, sparks, half-res glow, one `blendLinear` + `add` on the crop. Paints outside the person; inside only a rim band |
| 15 | Flash and shake | `super_saiyan_effect.render_super_saiyan`, `shake_frame` | <1 ms | `cv2.warpAffine` only when shake > 0 |
| 16 | HUD panel | `vanish_cam.render_status_panel`, `compose_dashboard` | ~1 ms, cached | Cache keyed by phase/action/camera/height/log; `--no-hud` disables it |
| 17 | Setup outline | `vanish_cam.draw_setup_marks` | <1 ms | HUD only; reuses the calibration mask, `cv2.boundingRect` |
| 18 | Camera picker | `vanish_cam.choose_camera_window`, `render_camera_panel` | only at startup | Live preview + list; A/D/arrows, Enter, Q |
| 19 | Sounds | `vanish_sound.VanishSound`, `super_saiyan_effect.write_*`, `dragonball_effect.write_teleport_sound` | generated once, then I/O | pygame mixer (`devicename` optional), `ffplay` fallback |
| 20 | Model download / verify | `vanish_cam.download_models`, `MODEL_URLS`, `MODEL_SHA256` | first run only | SHA-256 verified; no network after that |

## Detailed notes and optimization ideas

### 1. Gesture detection (the biggest CPU customer)

`InstantTransmissionDetector.detect` runs two MediaPipe VIDEO tasks on the same `mp.Image`: HandLandmarker (2 hands) and
FaceLandmarker (1 face). Measured on the owner's machine with a blank 960×540 frame: **~30.5 ms per call**. It runs at
12.5 Hz in Dragon Ball, so it alone can consume ~0.38 CPU-seconds per wall second. That is the first thing to profile
before touching the effects.

What is already done:

- One RGB conversion per frame (`frame_image` caches the `mp.Image`).
- The Super Saiyan pose reuses the teleport inference; no extra model run.
- `recent_faces` keeps the last face for 0.6 s when the fists hide it, so the charge pose and the aura keep working.
- Multi-view retries are only attempted after a failed detection and are spread over frames; the preferred view is
  cached.

Ideas, in order:

1. Lower the Dragon Ball check rate from 12.5 Hz to 10 Hz. The 1 s hold still gets ~10 samples and the 0.25 s grace
   covers a missed frame. Measure the CPU/UX trade-off with the owner.
2. Run the FaceLandmarker less often than the HandLandmarker. The face is only needed for the teleport pose and the
   charge pose; hand-only frames could reuse the last face (already done for the charge). Be careful: teleport detection
   needs a fresh face at the moment the hand touches the forehead.
3. Crop the upper body around the last face/hand box before detection, instead of the full frame. MediaPipe resizes
   internally, but a crop can improve both speed and small-hand recall. Keep timestamps monotonic and reset tracking
   when the crop changes.
4. Do not consider a C++/Rust rewrite first: MediaPipe and OpenCV are already native. The Python glue is not the
   bottleneck; the model calls are. A C++ port would only help if profiling shows Python-level per-pixel work.
5. If the gesture must feel snappier, decouple capture from inference with a worker thread that keeps the latest frame
   and result. MediaPipe tasks are not thread-safe per instance, but a single inference worker with a queue is viable.
   The UI loop can keep showing/streaming the last result at 30 FPS.

### 2. Person segmentation

`person_mask` calls `segment_for_video`, squeezes the model mask, blurs it **at model resolution** and resizes once to
the frame. This replaced a full-frame Gaussian blur and saved several ms per call.

What is already done:

- The mask is throttled: 0.05 s for vanish effects, 0.1 s for Super Saiyan, 0.3 s for calibration.
- Calibration reuses one mask for `person_in_frame` and `draw_setup_marks` (`person_in_frame(..., mask=...)`).
- `findNonZero` was replaced by `cv2.boundingRect(binary)` in hot paths (16× faster on a 960×540 mask).
- `HairTracker`/multiclass segmentation was removed; no second segmenter runs anymore.

Ideas:

1. Profile real frames: the blank-frame 6 ms is a lower bound. If the post-processing dominates, move more of it to
   the model resolution.
2. For `person_in_frame` only the area fraction matters: it could run on a downscaled image without upscaling the mask.
3. Keep the mask at 10 Hz during Super Saiyan; 20 Hz is only needed while the silhouette is moving in a vanish effect.
4. Reuse the mask bbox for all effects in the same frame (aura, teleport, setup outline) to avoid repeated
   `boundingRect` scans.

### 3. Super Saiyan aura

The aura is fully procedural (there is no GIF anymore). Second version (2026-10-29, branch `feat/ssj-realism`).

Per mask update (`AuraRenderer.geometry`, cached by mask identity, so 10 Hz under a 30 FPS output):

- `refine_person_mask`: at quarter resolution, `body_region` = the `head_ellipse` from the face landmarks plus
  everything below the eye line (`EYE_LINE`, rotated with the head); blurred, upscaled and multiplied into the
  segmenter mask. No background photo: the color-difference cut failed on the owner's setup (dark room, swivel chair,
  black hoodie on a black chair, close webcam with the shoulders above the chin) and painted the aura on the body.
- the golden hair (`HairOverlay.mask`) joins the silhouette when the hair level is ≥ 0.5, so the flames rise from
  the spikes.
- crop sized from the largest radius (flash × pulse) plus the flame rise, so the aura is never cut; a fade ramp keeps
  the field at zero on crop borders that are not the frame border;
- half resolution: outside and inside distance transforms, rim band (6 px, stronger at the top), contour points.

Per frame:

- darken the frame (`convertScaleAbs`, 28 % at full power) and copy the person back on the crop;
- ring `exp(-d / r)` with a 3 Hz pulse, rising flames with two vertical box blurs (anchored below), two scrolling
  noise textures sampled in frame coordinates (stable when the bbox moves);
- field → `cv2.LUT` with three flat tones and short anti-aliased steps; LUT entry 255 is the rim inside the person;
- sparks from a precomputed table;
- glow: the alpha blurred at half resolution (sigma 4), outside the person, added as warm light (`GLOW = 0.55`);
- one `cv2.blendLinear` + one `cv2.add` on the crop.

Measured on claude-bcn (no MediaPipe there): ~5.4–5.6 ms per frame with a new mask every third frame (main's
version: ~5.9 ms on the same CPU); not re-measured after the eye-line silhouette, which is cheaper than the old
background step. `tools/aura_preview.py` renders the look on a synthetic scene. `test_fast_enough_for_live_video` uses
a mask refresh every third frame, with a 20 ms budget.

Ideas:

1. Contour-mapped flame strip (`distanceTransformWithLabels` + `cv2.remap`), see HANDOFF-SUPER-SAIYAN.md §4.3.
2. Drop or reduce sparks on slow machines; they are cosmetic.
3. Expose the aura radius, darkening and tone colors as options if the owner wants to tune them without code.

### 4. Effects

- `render_teleport` already works on the person bbox and uses `cv2.boundingRect`.
- `apply_dissolve` works on the mask bbox but uses full-frame float arrays; integer blend or ROI-only compositing is a
  possible win.
- `speed_lines` generates ~width/7 lines with a Python loop; small but could be vectorized or cached per frame.
- Naruto smoke already limits its RGBA layer to the log area and caches the scaled log sprite.
- All effect caches (`log_cache`) are per-scale and should stay bounded.

### 5. HUD and composition

`render_status_panel` is ~1 ms, but it used to run every frame. It is now cached by
`(phase, action, camera, height, tuple(log lines))`; the log changes about once per second during calibration. Keep the
cache invalidation correct if you add fields to the panel.

`compose_dashboard` uses `np.hstack`, which allocates a new frame each time. A reusable output buffer would save an
allocation but not the copy; measure before changing it.

### 6. Porting to another language?

Only consider it after profiling with `cProfile`/`py-spy` on real frames. The heavy work is already in C++
(MediaPipe/OpenCV). A rewrite would be useful only for:
- a native extension for the aura/effect pixel maths (pybind11 + OpenCV), or
- a full C++ pipeline if you need to drop Python entirely for deployment reasons.

For a first pass, vectorized NumPy/OpenCV and caching will move the needle more than a port.

## Measured costs (indicative, owner's Ubuntu CPU)

| Operation | Time | Context |
|---|---|---|
| Hand + face detection | ~30.5 ms/call | blank 960×540 frame, after warm-up |
| Person segmenter inference | ~6.2 ms/call | blank 960×540 frame |
| `AuraRenderer.render` | ~11 ms/frame | 960×540, 190×390 person mask |
| `render_super_saiyan` | ~13.6 ms/frame | includes aura + flash + shake |
| `render_status_panel` | ~1.0 ms | 380×540, 24 log lines; cached in the loop |
| `cv2.boundingRect` vs `findNonZero` | 0.1 vs 1.7 ms | 960×540 binary mask |

These numbers are not a benchmark suite; they are a starting point. Re-measure on the target machine, with the app
running normally (camera + virtual camera), not only with synthetic frames.

## Benchmarking / profiling recipes

```bash
# Unit tests and resource check
.venv/bin/python -m unittest discover -p 'test_*.py'
.venv/bin/python vanish_cam.py --self-test

# Profile a real run (stop it with q or timeout)
timeout 20 .venv/bin/python -m cProfile -o /tmp/vanish.prof \
    vanish_cam.py --camera 4 --no-virtual-camera
.venv/bin/python - <<'PY'
import pstats
pstats.Stats('/tmp/vanish.prof').sort_stats('cumtime').print_stats(30)
PY
```

Useful micro-benchmarks live in the tests (`test_super_saiyan_effect.test_fast_enough_for_live_video`) and can be
adapted. When comparing changes, use the **minimum of several runs** or the median, not a single mean: the owner's
machine may be running other apps (including VanishCam itself).

## Invariants to preserve

- **No text or UI on the video** (preview or virtual camera). HUD goes on a separate panel; tests patch `cv2.putText`.
- **MediaPipe VIDEO timestamps must strictly increase.** Run each task at most once per frame. Reuse a mask/result
  instead of re-running a task with the same timestamp.
- **English** in code, docs, tests and terminal messages.
- **No frames to disk**, no network except model downloads (SHA-256 verified).
- **Keep the loop testable.** Patchable seams currently include: `gesture_active`, `person_mask`, `person_in_frame`,
  `create_tasks`, `open_camera`, `open_virtual_camera`, `VanishSound`, `teleport_sound_path`, `power_active`,
  `ssj_sound_paths`, `draw_setup_marks`, `render_status_panel`, `compose_dashboard`.
- **Virtual camera gets `display` only**, never the HUD or the setup outline.
- **Super Saiyan must not paint the person.** The aura is masked out inside the silhouette; keep it that way.

## File / symbol map

| File | Symbols worth knowing |
|---|---|
| `vanish_cam.py` | `run_camera` (loop), `person_mask`, `person_in_frame`, `GestureHold`, `apply_dissolve`, `make_dissolve_fields`, `render_status_panel`, `compose_dashboard`, `draw_setup_marks`, `choose_camera_window`, `open_camera`, `open_virtual_camera`, `power_active`, `download_models` |
| `dragonball_effect.py` | `instant_transmission`, `InstantTransmissionDetector`, `render_teleport`, `speed_lines`, `person_alpha`, `write_teleport_sound` |
| `naruto_effect.py` | `joined_hands_from_landmarks`, `substitution_anchor`, `render_substitution`, `render_reappearance`, `_smoke_layer`, `overlay_log` |
| `super_saiyan_effect.py` | `charge_pose`, `hand_tension`, `AuraRenderer`, `PowerState`, `render_super_saiyan`, `shake_frame`, `write_charge_sound`, `write_transform_sound`, `write_aura_hum` |
| `vanish_sound.py` | `VanishSound` (pygame/ffplay, loops, fades, device) |
| `test_video_output.py` | `run_loop` (fake clock, fake camera/segmenter/recognizer) |
| `test_super_saiyan_effect.py` | pose, power state, aura and performance tests |
| `assets/` | `teleport.mp3`, `ssj_transform.mp3` (owner-supplied, not MIT), `vanish.MP3`, `substitution_log.png`, `vanish_icon.png` |
| `models/` (gitignored) | downloaded segmenter + gesture model + generated sounds |

## Review checklist for the next optimization agent

1. Run the tests and the benchmarks above; record the baseline.
2. Profile a real run with the owner's camera (`--camera 4` on their machine) while idle and while transformed.
3. Attack the top of the profile, not the code that looks slow. The order is usually: hand/face detection, aura,
   segmentation, effect compositing, HUD.
4. After each change, run the unit tests, `--self-test`, and the real app for a few minutes.
5. Update this file and [CHANGELOG.md](CHANGELOG.md); keep [AGENTS.md](AGENTS.md) consistent.
