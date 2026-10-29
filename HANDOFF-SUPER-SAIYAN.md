# Handoff — Super Saiyan realism and real-time CPU performance

Written 2026-10-29 for the next coding agent. The **execution plan** (step-by-step checklist, §E) comes first; the
evaluation it is based on follows (§0–§8). Read [AGENTS.md](AGENTS.md) (rules, layout, testable seams),
[ALGORITHMS.md](ALGORITHMS.md) (measured costs) and [HANDOFF.md](HANDOFF.md) (general status) first. Keep everything
you write in the repo in English.

## E. Execution plan

Branch: **`feat/ssj-realism`** (the owner merges into `main`). Target platforms, in order: **Ubuntu and Windows
first**; macOS only in phase E5, after the owner has approved the result on both. Tick a box only when its check has
actually been run; write what you measured next to it. Every phase ends with a gate the owner has to pass.

Checks that apply to every step: the full test suite passes (`.venv/bin/python -m unittest discover -p 'test_*.py'`),
new pure functions have tests, CI is green on `ubuntu-latest` and `windows-latest` (macOS jobs may stay red/cancelled
until E5, see §0), CHANGELOG.md (*Unreleased*) is updated, and new costs go into ALGORITHMS.md.

### E1 — Visual foundations (§4.1, §4.2, §6.3)

- [x] **E1.1 The aura is not clipped by its crop.** Margins derived from the maximum aura radius plus the flame rise;
  the field fades to zero before the crop border. *Check:* unit test — along the crop border the added light is 0;
  render of the synthetic scene shows no straight vertical/horizontal cut.
  *Done `6c8c7f3`: `test_not_cut_by_its_crop` passes. The old version's cut was reproduced on a render of the
  synthetic scene; the render of the new version is still pending (see E1.6).*
- [x] **E1.2 Geometry cached per mask update.** Distance transforms, person mask at half resolution, rim and contour
  points are recomputed only when a new mask arrives (10 Hz), not per output frame (30 Hz); compositing is
  `cv2.blendLinear`/uint8. *Check:* unit test that a second frame with the same mask does not recompute the geometry;
  `test_fast_enough_for_live_video` budget lowered and passing; ms/frame before/after in ALGORITHMS.md.
  *Done: `test_geometry_is_cached_per_mask`; budget 40 → 20 ms with background + mask refresh every 3rd frame;
  claude-bcn 3.9 ms cached / 4.9 ms with refreshes vs 5.9 ms on main (same CPU). Owner-CPU numbers pending (E2.1).*
- [x] **E1.3 Static furniture removed from the silhouette.** `refine_person_mask(mask, frame, background, head)`: keep
  only segmenter pixels that differ from the calibrated background, always keep a head/hair ellipse from the face
  landmarks, fill holes, drop small fragments; return the input mask unchanged when the background is stale (camera
  moved, light changed) or no face is known. *Check:* unit tests on a synthetic chair: chair removed, dark hair in front
  of a dark chair kept, stale background → unchanged, no face → unchanged.
  *Done: `SilhouetteTests` (5 tests, incl. a shirt patch with the wall's color → no hole). Wired in `run_camera` with
  `latest_faces` + `head_ellipse`. Risk to watch on hardware: lighting changes after calibration (auto-exposure) can
  mark the background stale → falls back to the plain segmenter mask (chair back again, nothing breaks).*
- [x] **E1.4 Darker surroundings while transformed.** Outside the person, the frame is darkened proportionally to the
  aura intensity (~25 % at full power). *Check:* unit test — a far background pixel is darker, the person's interior is
  unchanged, intensity 0 changes nothing.
  *Done: `DARKEN = 0.28`; `test_surroundings_darken_with_the_power`; intensity 0 returns the frame untouched
  (`test_no_intensity_no_change`).*
- [x] **E1.5 Rim light on the person.** Warm light in a thin band inside the silhouette edge, stronger at the top;
  exactly zero deeper inside. *Check:* unit test — edge pixel warmer, interior pixel identical.
  *Done: `RIM_WIDTH = 6` (half res), `RIM_ALPHA = 0.45`; `test_rim_light_only_along_the_inside_edge`,
  `test_does_not_paint_the_person`.*
- [x] **E1.6 Cel-shaded aura with flame tongues all around.** 3 flat tones (gold, yellow, near-white inner rim) with
  short anti-aliased steps, drawn with alpha (visible on light walls, not only additive), tongues from upward-stretched
  scrolling noise sampled in frame coordinates (stable when the bbox moves), tighter than today. *Check:* renders of the
  synthetic scene on a light wall and a dark wall attached to the PR/commit message description; unit test that the
  aura is yellow next to the silhouette, rises above the head and is zero far from it.
  *Code and unit tests done (`test_glows_yellow_next_to_the_silhouette_and_rises`,
  `test_light_wall_still_shows_a_yellow_aura`). Renders with `.venv/bin/python tools/aura_preview.py aura.png`
  (synthetic light/dark wall + chair + dark hair; columns: two times with the background plate, one without). First
  render looked muddy (ochre/pastel, uniform band); tuned to saturated tones, a more transparent outer tone, bigger
  tongues (`AURA_RADIUS 10`, `FLAME_RISE 4.5`, coarser noise) and a half-res additive glow (`GLOW`). Second render:
  bright yellow flames that read as light on both walls, chair not wrapped with the plate. Further tuning (taller
  plume above the head, colors) belongs to the owner gate. Cost ~5.5 ms/frame on claude-bcn vs 5.9 ms on main.*
- [x] **E1.7 Docs.** README + GUIDE: turn off background blur/replacement in Meet/Zoom/Teams while using VanishCam;
  the status panel says so while transformed. CHANGELOG + ALGORITHMS updated.
- [ ] **E1.8 Gate (owner):** Ubuntu and Windows, real camera, Meet with background effects off: one screenshot on a
  light wall, one in a darker room. Chair not wrapped, no visible lag in the aura when moving, no FPS drop compared to
  `main`. Iterate on the look until the owner approves.

### E2 — Fluidity (§5, §6)

- [ ] **E2.1 Benchmark harness.** `--input-video PATH` (frames from a file, never written back) and `--bench N`
  (per-stage p50/p95 ms and process CPU %). *Check:* runs on an owner-recorded clip on Ubuntu and Windows; baseline
  numbers committed to ALGORITHMS.md.
- [ ] **E2.2 Capture thread** that keeps only the latest frame. *Check:* unit test with a fake slow camera; bench shows
  no queued/stale frames.
- [ ] **E2.3 Async inference** (`RunningMode.LIVE_STREAM`, `detect_async`/`segment_async`, latest result reused).
  *Check:* bench p95 frame time < 33 ms on the owner's machines; loop tests still pass with the fake clock.
- [ ] **E2.4 Adaptive detection** (4–5 Hz with no hands, 12–15 Hz with hands, full rate during a hold; thumbnail motion
  gate; face model only when a hand is near the head). *Check:* bench idle CPU before/after; owner confirms teleport,
  Super Saiyan and power-down still trigger reliably.
- [ ] **E2.5 Small items** (preview at 15 FPS, camera at working resolution, `apply_dissolve` uint8/ROI, cached speed
  lines). *Check:* bench before/after.
- [ ] **E2.6 Gate (owner):** bench numbers on Ubuntu and Windows in ALGORITHMS.md; no perceived latency on gestures.

### E3 — Realism 2: flames mapped to the contour, eyes (§4.2, §4.3)

- [ ] **E3.1 Contour mapping with a procedural tileable strip** (`distanceTransformWithLabels` + arc length +
  `cv2.remap`). *Check:* unit tests (never inside the person, wraps around the whole outline, deterministic); renders.
- [ ] **E3.2 Pre-rendered flame strip asset** (fire simulation with a toon shader, looping, tileable, < 3 MB, origin in
  NOTICE.md). *Check:* loop has no visible seam; cost per frame ≤ E1 aura.
- [x] **E3.3 Iris tint** (teal/green, luminance-preserving, FaceLandmarker iris points 468–477). *Check:* unit test on
  synthetic landmarks; owner screenshot. *Done early at the owner's request, with golden brows (`ssj_face.tint_eyes`,
  `tint_brows`): iris ∩ eye opening, pupil kept darker; brows only where darker than the surrounding skin.
  `EyesAndBrowsTests`; owner screenshot pending (E4.4).*
- [ ] **E3.4 Gate (owner)** on Ubuntu and Windows.

### E4 — Golden hair (§4.4)

- [x] **E4.0 Owner decision (2026-10-29):** personalised AI hair, via **import**: VanishCam takes the photos, the user
  runs them through ChatGPT/Gemini themselves and drops the results in `ssj_hair/`. VanishCam opens no network
  connection and holds no API key. No local recolor for now. The owner also asked for the eyes and brows now (E3.3).
- [x] **E4.1 Guided photos.** `--ssj-hair-photos` (`vanish_cam.capture_hair_photos`): front + both sides, SPACE/S/Q,
  same mirroring as the live detection, writes `ssj_hair/photo_*.jpg` + `prompt.txt` and prints the steps.
  *Check:* `HairPhotoTests.test_guided_photos_skip_and_prompt`.
- [x] **E4.2 Import.** `ssj_face.load_hair_views`: FaceLandmarker (IMAGE mode, `vanish_cam.detect_face_points`) on
  each `ssj_*` picture; `hair_mask` = Lab gold test (`b > 25`, `b − a > 22`, `L > 90`) minus the lower face, closed,
  only pieces touching the head, holes filled; cut-out + anchor points + yaw cached in `ssj_hair/.cache/` (invalidated
  by size/mtime). Clear terminal messages for "no face" / "no golden hair". *Check:* `HairImportTests` (lamp far from
  the head ignored, highlight inside the hair kept, cache reused, problems reported).
- [x] **E4.3 Live fit.** `HairOverlay`: `estimateAffinePartial2D` (LMEDS) from 9 anchors (eye corners, nose, forehead,
  chin, cheeks) to the live face, warp only the bbox, alpha blend; view picked by nearest yaw. Hair, eyes and brows
  flicker in late in the charge (`PowerLevels.hair`). *Check:* `HairOverlayTests`, `TransformationTimelineTests`;
  synthetic render (rotated 10°, scaled 0.9) fits the head and covers the real hair.
- [ ] **E4.4 Gate (owner):** run `--ssj-hair-photos`, make the pictures, check the look on Ubuntu and Windows.
  Known risks to watch: (a) a warm-lit forehead in the generated picture may be taken as hair; (b) the real hair can
  peek out where the generated hair is smaller; (c) fixed by `ssj_motion.HeadTracker` (the hair, eyes and brows
  follow a face predicted every frame instead of holding at 12.5 Hz); (d) in a PyInstaller one-file build `APP_DIR` is a temporary
  folder, so `ssj_hair/` must move to a user data folder before shipping binaries.

### E5 — macOS (after E1–E3 are approved on Ubuntu and Windows)

- [ ] E5.1 Owner fixes the `macos-latest` CI runner issue (§0); CI green on arm64 and Intel.
- [ ] E5.2 `install.sh` end to end on a real Mac, OBS virtual camera, Meet test.
- [ ] E5.3 Audio: watch for the duplicate SDL2 crash (HANDOFF.md §1). E5.4 `.app` build (`BUILD_MACOS.sh`).

### E6 — Windows camera picker and a home window for all settings (IN PROGRESS, same branch)

Owner request (2026-10-29): on Windows the camera picker must work like on Ubuntu, with real camera names, and all the
setup (effect, camera, golden hair) must be done from a window, not from command-line flags. Everything stays on
`feat/ssj-realism` so the owner can test it all together. Today on Windows there is **no picker**: `open_camera` only
lists cameras on Linux (`find_linux_cameras`), so Windows always opens index 0 unless `--camera N`; `--list-cameras` is
Linux-only. Trap: **OBS Virtual Camera is a DirectShow camera too**; if VanishCam opens it, it reads its own output.

- [x] **E6.1 Dependency.** `pygrabber==0.2; sys_platform == "win32"` (MIT; pulls `comtypes` 1.4.17, MIT) in
  `requirements.txt`; lock regenerated with `--python-version 3.10` (without it uv drops the Python 3.10 variants
  and breaks Ubuntu 22.04). Only `pygrabber` and `comtypes` were added to the lock. Both are in NOTICE.md and
  CHANGELOG.
- [x] **E6.2 Camera discovery for every OS** in `vanish_cam.py`:
  - `windows_camera_names()`: `from pygrabber.dshow_graph import FilterGraph; FilterGraph().get_input_devices()`
    inside `try/except Exception` → `None` on failure (FilterGraph also creates a Windows Media profile manager, which
    may be missing on Windows "N" editions). The list is in DirectShow order = the index OpenCV uses with
    `cv2.CAP_DSHOW` (which `_open_capture` already tries first).
  - `find_windows_cameras(names=None, probe=None) -> list[(index, label)]`: drop virtual cameras by name
    (case-insensitive: "virtual", "obs", "unity video capture", "vanishcam"); if `names` is `None`, probe indices 0–4
    with `_open_capture` and label them "Camera N".
  - `find_cameras(system)`: Linux → `[(device, linux_camera_label(device))]`; Windows → `find_windows_cameras()`;
    macOS → `[]` for now (E5).
  - `open_camera`: use `find_cameras`; >1 → `choose_camera_window`; 1 → that one (on Windows this skips OBS at index
    0); none → 0. Put the real name in `info["label"]`.
  - `choose_camera_window` and `render_camera_panel` take `[(source, label)]` instead of bare sources (only callers:
    `open_camera`; no tests use them yet).
  - Rename `list_linux_cameras` → `list_cameras` (callers: `open_camera` error path and `run` for `--list-cameras`)
    and print `--camera N` hints for Windows too.
  - *Check:* unit tests with fake names (`["OBS Virtual Camera", "Integrated Camera", "Logitech C920"]` → indices 1
    and 2 with their names), probe fallback, and `open_camera` picking the only real camera.
  *Done on Windows (owner's PC): `WindowsCameraTests`. Changes from the plan: "meta quest" is also in
  `VIRTUAL_CAMERA_WORDS` (the owner's PC lists Meta Quest 3/3S/2/Pro as DirectShow cameras, all before the webcam);
  when Windows lists only virtual cameras, `open_camera` prints them and stops instead of opening index 0 (that would
  read a headset or OBS's own output); `camera_label` names an explicit `--camera N` too. On the owner's PC
  `--list-cameras` shows only `3  Camera (NVIDIA Broadcast)`: their webcam is reached through NVIDIA Broadcast.*
- [x] **E6.3 Home window** (new module `home_ui.py`, OpenCV-drawn like `choose_mode`, ASCII text only):
  - Sections: EFFECT (Dragon Ball / Normal / Naruto, keys 1–3), CAMERA (current name + "Change" → the picker;
    hidden when only one camera), SUPER SAIYAN HAIR (Dragon Ball only: status "N pictures ready" / "not set up" /
    last problem; buttons "Take photos", "Copy prompt", "Open folder", "Check pictures"), a message area (last 4
    lines) and a big START button (Enter). Q/ESC or closing the window quits.
  - `run_home(settings, actions)` returns the chosen settings or `None`; `actions` are callbacks from `vanish_cam`
    (choose camera, take photos, copy prompt, open folder, check pictures) so the module stays testable.
  - "Take photos" reuses `capture_hair_photos`, which must close only its own window (`cv2.destroyWindow`, not
    `destroyAllWindows`) and return the saved paths instead of printing only. "Check pictures" runs
    `ssj_face.load_hair_views` with a log collector and shows the messages in the window.
  - Helpers: `copy_text(text) -> bool` (Windows `clip`, macOS `pbcopy`, Linux `wl-copy` / `xclip -selection clipboard`
    / `xsel --clipboard --input`; the prompt is ASCII), `open_folder(path)` (Windows `os.startfile`, macOS `open`,
    Linux `xdg-open`, non-blocking).
  - Remember the last effect and camera **name** (indices can change) in `vanishcam_settings.json` in the app folder
    (gitignore it).
  - *Check:* unit tests for layout hit-testing, keys/mouse flow with patched `cv2` (pattern: `test_video_output.py`
    and the `choose_mode` tests in `test_naruto_effect.py`), settings round trip, `copy_text` fallbacks.
  *Done: `home_ui.py` + `test_home_ui.py`. Keys: `1`-`3` effect, `W` camera, `T`/`P`/`O`/`H` hair actions, Enter
  START, Q/ESC quit. `take_hair_photos` (returns paths, closes only its window) is the core and `capture_hair_photos`
  the CLI wrapper; `hair_status`, `check_hair_pictures`, `home_actions`, `initial_home_settings`, `run_home` live in
  `vanish_cam.py`. A failing action shows "Problem: ..." in the window instead of closing it.*
- [x] **E6.4 Wire it.** New flag `--home`; `run()` shows the home window and then starts `run_camera` with the chosen
  mode/camera. Launchers open the home window **when started without arguments**: `vanishcam.bat` (keep it pure
  ASCII + CRLF) and `vanishcam.sh` (the Ubuntu menu entry and the Windows desktop shortcut call them without
  arguments). Any explicit flag keeps today's behaviour. *Done: `HOME_WINDOW` in `vanishcam.bat`, `args=(--home)`
  in `vanishcam.sh`. `AVVIA_*.bat` forward `%*`, so they open the home window too when called bare.*
- [ ] **E6.5 Docs + gate.** README/GUIDE: "open VanishCam from the shortcut/menu, everything is in the window";
  AGENTS layout + seams; CHANGELOG; NOTICE. *Owner gate on Windows:* the picker lists the real webcams by name
  without OBS Virtual Camera, the home window works with the mouse, the hair flow can be done without the terminal.
  *Docs done. Owner gate pending.*

### Resume on Windows (owner's machine, from 2026-10-29)

The owner continues on Windows with a new Claude Code session (the claude-bcn session cannot run on their PC). State
at handoff: branch `feat/ssj-realism`, everything committed and pushed, CI green on Ubuntu, Windows and macOS arm64.
Done: E1.1–E1.7, E3.3, E4.0–E4.3, E6.1–E6.4 and the E6.5 docs. **Next:** the owner gates E6.5 (home window and
picker), E1.8 (aura) and E4.4 (hair, eyes, brows) on Windows, then the same on Ubuntu, then merge (the owner merges)
and E2. The hair flow is now done from the home window (Desktop shortcut) instead of `--ssj-hair-photos`.

Known install problems on the owner's PC (not fixed in the repo yet, ask before changing the installer):
- HTTPS is intercepted by a local root certificate (antivirus/proxy) that only the Windows store trusts: `git clone`
  needs `-c http.sslBackend=schannel` and uv needs `UV_SYSTEM_CERTS=1` (or the deprecated `UV_NATIVE_TLS=1`).
- `install.ps1` throws "Failed: install uv" right after uv installs successfully: `Check` reads a stale
  `$LASTEXITCODE` after `Invoke-Expression` of the uv installer. Rerunning the script works (uv is then found).

Setup in PowerShell (not as administrator), in a separate folder so an existing install is not touched:

```powershell
winget install --id Git.Git -e            # only if git is missing; reopen PowerShell afterwards
git clone -b feat/ssj-realism https://github.com/Agupane/vanish_webcam.git $HOME\VanishCam-ssj
cd $HOME\VanishCam-ssj
powershell -ExecutionPolicy Bypass -File .\install.ps1   # uses this folder; repoints the Desktop shortcut here
```

Run and check:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -p "test_*.py"   # 111 tests expected to pass
.\.venv\Scripts\python.exe tools\aura_preview.py --show           # synthetic aura preview, no camera
.\vanishcam.bat --ssj-hair-photos   # SPACE take, S skip, Q quit; prints the prompt (also ssj_hair\prompt.txt)
# owner: make ssj_hair\ssj_front.png (+ ssj_left.png, ssj_right.png) with ChatGPT/Gemini
.\vanishcam.bat                     # terminal must say "Golden hair ready"
```

In Meet/Zoom pick **OBS Virtual Camera** (do not start OBS's own virtual camera) and **turn off background blur**.
Take the background photo with the chair in place. Ask the owner for screenshots: light wall and darker room,
transformed, moving the head. What to look for: chair not wrapped, aura not lagging, FPS like `main`, hair fitted on
the head (no forehead taken as hair, real hair not peeking out), teal irises, golden brows, the flicker late in the
charge. Tune in `super_saiyan_effect.py` (`AURA_TONES`, `AURA_RADIUS`, `FLAME_RISE`, `DARKEN`, `GLOW`) and
`ssj_face.py` (`EYE_COLOR`, `BROW_COLOR`, `hair_mask` thresholds). After pulling new commits: `git pull`; rerun
`install.ps1` only if `requirements.lock.txt` changed. Keep `.bat`/`.ps1` files pure ASCII.

### Progress log

- 2026-10-29: plan written; E1 started on `feat/ssj-realism`.
- 2026-10-29: E1.1–E1.5 and E1.7 done, E1.6 code done (renders pending); 97 tests pass on claude-bcn (Linux). Next:
  E1.6 renders and tuning, CI on Ubuntu + Windows, then the owner gate E1.8.
- 2026-10-29: E1.6 rendered and tuned. The workflow now also runs on pushes to `feat/**` (no `gh` token on claude-bcn
  to open a PR). Next: CI result on Ubuntu + Windows, then the owner gate E1.8.
- 2026-10-29: CI on `5af85f8`: `ubuntu-latest` ✅, `windows-latest` ✅ (unit tests + `--self-test` with the real
  MediaPipe models). macOS jobs still queued (runner issue, §0). **Waiting for the owner gate E1.8.**
- 2026-10-29: owner asked about hair and eyes; decided the import approach (E4.0). E3.3 + E4.1–E4.3 done in
  `ssj_face.py`; 111 tests pass on claude-bcn. Owner gates E1.8 and E4.4 can be done in the same session.
- 2026-10-29: CI on `fbe2b51`: `ubuntu-latest` ✅, `windows-latest` ✅ and, this time, `macos-latest` (arm64) ✅ too:
  the runner was assigned, so the §0 issue looks intermittent (runner availability), not the code.
- 2026-10-29: owner asked for the Windows camera picker with names and a home window for all settings (E6). Done:
  E6.1 (dependency + lock). **Next: E6.2–E6.5** — the owner continues from Windows, where the picker can be tested
  for real (`pygrabber` only works there). On Windows, rerun `install.ps1` after `git pull` because the lock changed.
- 2026-10-29 (Windows session on the owner's PC): installed in `%USERPROFILE%\VanishCam-ssj`. E6.2–E6.4 and the E6.5
  docs done; 135 tests, 134 pass and the Linux sysfs test now skips itself where symlinks are not allowed (Windows
  without Developer Mode). Next: owner gate E6.5, then E1.8 and E4.4.
- 2026-10-29: home window buttons fixed (act on press; the owner's touchpad drifted between press and release).
  First E1.8/E4.4 round on Windows (Meet, `ssj_hair/meet1.png` light wall, `meet2.png` dark room; personal, not
  committed): golden hair fits well, real hair hidden, teal eyes OK. Problems: (1) the chair was still in the
  silhouette in the dark room (plate stale -> raw segmenter) and (2) in the light room the color difference cut holes
  in the black hoodie in front of the black chair, so the aura painted blocky patches on the body; (3) the spikes
  covered the aura instead of being surrounded; (4) brows read as flat painted bars. Fixed: `body_region` (head
  ellipse + neck strip + shoulder cone from the face) replaces the color cut, the plate only adds back moved parts
  (raised arms); `HairOverlay.mask` joins the silhouette once the hair is in (`levels.hair >= 0.5`); brows at
  `BROW_OPACITY = 0.6` with more of their own shading. 141 tests. Next: second owner round with screenshots.
- 2026-10-29: second round (`meet3.png`, `meet4.png`, light room only): the aura around the hair looks right, but the
  shoulder cone was wrong for this camera: a close webcam above the face sees the shoulders *above* the chin, so they
  were cut and painted yellow; the swivel chair moves when the owner turns, so the plate add-back brought back jagged
  chair pieces. Replaced by the simplest rule that never cuts the body: above `EYE_LINE` only the head ellipse, below
  it the segmenter as is (`body_region`); the background photo is no longer used by the aura (parameter removed from
  `refine_person_mask`, `AuraRenderer` and `render_super_saiyan`). The chair below the eyes stays in the silhouette:
  acceptable, the aura wraps it like broad shoulders. 139 tests. Next: third round, including the dark room.
- 2026-10-29: version shown in the home window, side panel and terminal (`app_version`: git commit + date).
  Third round (`meet5.png` light wall, `meet6.png` dark room, version `3c79082`): no more patches on the body, hair,
  eyes and brows fine in both rooms. Left: a flat shelf at the eye line where the chair is cut, which the aura turned
  into a boxy outline in the dark room. Fixed with `BODY_SLOPE`: below the eye line the allowed width grows from the
  head's at 3 px per px down, so the chair is cut along a shoulder-like slope. 142 tests. Next: owner approval of
  E1.8/E4.4/E6.5 on Windows, then Ubuntu.
- 2026-10-29: owner (fair hair, green eyes) asked to switch off the eye/brow tint: `HomeSettings.eyes/brows`
  checkboxes (`E`/`B`, saved in `vanishcam_settings.json`), `--no-ssj-eyes` / `--no-ssj-brows`,
  `render_face(..., eyes, brows)`. Power-down with the two fists was hard because the aura painted over the raised
  fists (above the eye line, outside the head ellipse; detection itself uses the clean camera frame): `hands_mask`
  (hand landmark hulls, padded, intersected with the segmenter) joins the silhouette via the aura's `extra`.
  147 tests. Owner also asked for animated hair that follows the head smoothly (plan being analyzed).
- 2026-10-29: hair motion done (owner: "dale todo"), new `ssj_motion.py` + `test_ssj_motion.py`. Causes found: the
  face held for 2-3 frames then jumped (12.5 Hz detection, no prediction); LMEDS on 9 points flipped inliers; the
  chin made the hair change size when talking; hard view switches; rigid hair. Done: weighted Procrustes
  (`ANCHOR_WEIGHTS`, chin 0.05), `HeadTracker` (alpha-beta on centre/angle/log-scale measured at the anchors'
  centre, `TRACK_ALPHA_MIN 0.4`, speed-adaptive, decaying prediction ≤ 0.15 s; fed only new detections via the
  detector's `last_good_face_ms`, list identity for a Mock), `HairDynamics` (spring, kick in `transform`),
  `HairOverlay.select` (hysteresis + 0.2 s fade), `hair_warp_maps` (roots fixed via `root_weights`, sway, roll,
  flutter scaled by `levels.aura`), one `PlacedHair` shared by aura and drawing; eyes, brows and the head ellipse use
  the tracked face. Not done on purpose: optical-flow tracking between detections (plan P3) — only if the owner still
  sees the hair slide after this. 167 tests; +2 ms/frame on the owner's CPU. Next: owner screen recording (fast head
  turns, talking, power up/down) to tune `SWAY_*`, `FLUTTER_*`, `TRACK_*`.
- 2026-10-29: owner video (`ssj_hair/video.mp4`, 14 s, version `72c586f`, webcam now AUKEY PC-LM6): consecutive frames
  move smoothly, no jumps. Two defects: (1) the view crossfade showed both pictures see-through with doubled spikes ->
  `VIEW_FADE_SECONDS 0.1`, `VIEW_SWITCH_HOLD 0.25`; (2) pale patches at the hair tips: the hair counted as body, so
  the room behind its see-through tips was not darkened and got the rim light -> `AuraRenderer` `cover` (hair: aura
  goes around it, room darkened, no rim) separate from `extra` (hands: body).

## 0. Start here

- Repo: `Agupane/vanish_webcam`, branch `main`. Local clone: `/root/work/repos/vanish_webcam` on claude-bcn,
  `/workspace/vanish_webcam` in OpenCode.
- Tests: `.venv/bin/python -m unittest discover -p 'test_*.py'` (Linux needs `libegl1 libgles2`).
- MediaPipe crashes in headless containers without GPU/display (`malloc(): unaligned tcache chunk`); that is the
  environment. Pure NumPy/OpenCV code (the aura, the state machine) can be tested anywhere; anything that runs a
  MediaPipe task must be verified in CI or on the owner's machine.
- **CI is red, but not because of the code:** since `b4e91c8` every run has `test (macos-latest)` *cancelled after 15
  minutes with no runner assigned* (no steps ran). Ubuntu, Windows and macOS Intel are green. Likely macOS minutes or
  runner availability on the account; the owner has to check GitHub billing. Do not "fix" it in the workflow without
  asking. HANDOFF.md still says the matrix is green: correct it once the cause is known.
- The owner confirmed on 2026-10-29 that **the Super Saiyan gesture works well**. Do not change the pose detection
  (`charge_pose`, `hand_tension`, thresholds) unless a change below requires it, and then re-verify with the owner.
- Commit in small steps, keep the 87+ tests green, add tests for every new pure function, update CHANGELOG.md
  (*Unreleased*) and NOTICE.md (new models/assets), and update ALGORITHMS.md with new measured costs.

## 1. What the owner sees today (screenshot of a Google Meet call, 2026-10-29)

The owner sent a photo of the screen during a Meet call with the aura on. Observations:

1. **Meet's background blur was on.** Meet segments the person and blurs everything else, so it smeared the aura
   (which lives outside the person) into a soft haze. Parts of the aura near the body were kept sharp, others were
   blurred: the result looks like dirty lens flare. Any aura design must assume the call app's background effects are
   **off**; the README/GUIDE and the status panel must tell the user to turn off background blur/replacement in
   Meet/Zoom/Teams while using VanishCam.
2. **Washed out on a bright wall.** The background is a light grey/white wall. The additive glow saturates to white
   and has almost no contrast; it reads as overexposure, not as an energy aura.
3. **Shapeless, very wide halo.** A large soft yellow cloud spreads far above and left of the head (about one head
   width or more). There are no flame tongues, no defined edge and no bright rim hugging the body.
4. **Asymmetric flames.** The only fire-like part is a cluster of orange/yellow flames on one side, next to the arm and
   the torso. The rest of the outline has almost nothing. Investigate why (candidates: the vertical `rising` filter and
   the bbox crop margins `-70/-170/+70/+15` in `AuraRenderer.render`; the mask shape between arm and torso; the chair
   being part of the mask; the preview/output mirror). Reproduce with a synthetic mask first.
5. **The chair is part of the silhouette.** The owner sits in a high-back gaming chair; the person segmenter treats
   the chair as "person", so the aura wraps the chair instead of the body.
6. **Nothing changes on the person.** Same hair, same eyes, no light on the skin. It looks like a filter on the
   background, not a transformation.

Do not commit the screenshot: it shows the owner's face and the repo is public.

## 2. How the Super Saiyan effect works now

File `super_saiyan_effect.py`, called from `vanish_cam.run_camera` (search `ssj.render_super_saiyan`).

- **Pose:** both clenched fists in front of the face, held 1.5 s (`charge_pose`, `hand_tension`). Reuses the Dragon
  Ball hand + face landmarker result (`power_active`), no extra model.
- **State machine:** `PowerState`: `off → charging → flash → super → powering_down`; `PowerLevels` gives aura
  intensity, flash, shake and radius per phase.
- **Mask:** `vanish_cam.person_mask` (MediaPipe `selfie_segmenter_landscape`, 256×144 model output, blurred at model
  resolution and upscaled), refreshed every **0.1 s** during the transformation (`update_mask(0.1)`).
- **Aura (`AuraRenderer.render`), every output frame:**
  1. crop the mask bbox with margins, downscale to half resolution (`AURA_SCALE = 0.5`);
  2. outside distance transform → ring `exp(-d / AURA_RADIUS)` (`AURA_RADIUS = 22`, pulsing ±15 % at 3 Hz);
  3. "rising flames": vertical `filter2D` with a 26-row kernel, `max(ring, rising * 1.3)`;
  4. multiply by a 256×256 value-noise texture scrolled upward (one rigid texture for the whole aura);
  5. map through `AURA_LUT` (black → orange → yellow → near white), 30 sparks of 1–2 px along the contour;
  6. zero inside the person (`glow *= 1 - person`), upscale, **add** to the frame (float32).
- **Flash:** whitening on transform; **shake:** `warpAffine` with random offset; sounds synthesized or
  `assets/ssj_*.mp3`.
- History: a GIF aura and a golden-hair/spiky-crest pipeline (multiclass hair segmentation) were removed in `ffb1ef5`
  because they painted the person and looked wrong. Do not bring them back as they were.

## 3. Visual goal and gap

| In the series | Today |
|---|---|
| Aura with sharp, flame-like tongues rising upward, cel-shaded with 2–3 flat tones and a bright white/yellow inner rim hugging the body | Soft additive gradient; the scrolling noise reads as a texture sliding, not as flames |
| Golden spiky hair — the main signifier | None (removed) |
| Teal/green irises, golden eyebrows | None |
| The aura **lights the character**: yellow rim light on face/body, darker, more contrasted surroundings | The person is never touched; on light walls the glow disappears or washes out |
| Lightning (SSJ2), dust and pebbles floating up, camera shake, flash | Shake and flash exist; 30 tiny sparks |

## 4. Visual plan (in order; each step is shippable on its own)

### 4.1 Fix the foundations

- **Better silhouette using the calibrated background.** VanishCam already captures a clean background plate during
  setup. The chair is static, so it is in the plate. Person mask = `segmenter_mask ∧ (|frame − background| > threshold)`
  (difference computed at low resolution, morphological close, temporal smoothing). This removes the chair and other
  static furniture. Fall back to the plain segmenter mask when the background is stale (camera moved, lighting
  changed: high difference everywhere).
- **Temporal stability:** exponential moving average of the mask between updates; 15–20 Hz during the transformation
  (the segmenter is cheap, ~6 ms) so the aura does not lag when the owner moves.
- **Never paint with a stale mask:** when the mask is older than the frame, dilate the "keep out" zone a little.
- **Blend that survives light backgrounds:** darken and slightly desaturate the background outside the person while
  transformed (−15 to −25 %, plus a vignette), then use a screen blend (or additive capped per channel) for the aura.
  The series darkens the surroundings; this is what gives the aura contrast.
- **Docs:** tell users to disable Meet/Zoom/Teams background blur/replacement (README, GUIDE, status panel hint while
  transformed). Optionally detect nothing — we cannot see the call app — just document it.

### 4.2 Light the person (biggest realism gain per effort)

- **Rim light:** inside distance transform of the person mask; add warm yellow light in a band of ~6–15 px inside
  the silhouette edge, stronger on top (light comes from the aura around). This is lighting, not painting: it must keep
  the person's texture (multiply/screen at 20–35 %, not opaque color).
- **Warm tint on the face/upper body** at low opacity, pulsing with the aura.
- **Eyes:** FaceLandmarker returns 478 points including the irises (468–477). Tint the iris disc teal/green with a
  luminance-preserving blend; optional golden eyebrows (eyebrow landmarks + small dilated mask).

### 4.3 Cel-shaded flame aura mapped to the silhouette

Two options; the second is the recommendation.

- **Procedural flames:** emit flame polygons from contour points, bent upward, length modulated by animated noise and
  by the contour normal's vertical component (longer on top and shoulders, short at the bottom); fill with 2–3 flat
  tones + white inner rim; slight blur. Cheap, no assets.
- **Pre-generated flame strip mapped along the contour (recommended):**
  1. Offline, produce a **horizontally tileable, looping flame strip** with alpha (e.g. 24 frames of 1024×256 RGBA,
     anime cel-shaded, flames pointing "up" = away from the body).
  2. Per mask update (10–20 Hz), at half resolution: `cv2.distanceTransformWithLabels(outside, DIST_L2, 3,
     labelType=DIST_LABEL_PIXEL)` gives, for every outside pixel, its distance `d` to the silhouette and the label of
     the nearest contour pixel. Order the contour pixels by arc length so each label maps to `s` (position along the
     outline). Build `map_x = s * strip_width / perimeter` (wrapping) and `map_y = d * strip_height / max_thickness`,
     plus an upward shear term so flames lean up regardless of the normal.
  3. Per output frame: `cv2.remap` the current strip frame with those maps (~1–2 ms at half resolution), mask out the
     person, composite.
  The aura then follows any pose and can never enter the person — the problem that killed the GIF.
- **Asset generation:** image/video models (Veo, Kling, Runway, Flux…) are good for style references and key frames
  but bad at seamless loops and alpha; if used, generate on pure black and derive alpha from luminance. The most
  reliable way to get looping, tileable flames with real alpha is a **fire simulation** (EmberGen or Blender
  Mantaflow) rendered with a toon/posterize shader into 2–3 flat tones. Store the result in `assets/` as a PNG/WebP
  sprite sheet; keep it small (< 3 MB).
- Extra pre-generated assets with the same technique: transformation burst (flipbook), lightning bolts (SSJ2 variant),
  floating dust/pebbles.
- **Licensing:** assets must be original (simulated or generated by us), never frames cut from the anime (see
  AGENTS.md rules). List every new asset and its origin in NOTICE.md.

### 4.4 Golden hair (optional, opt-in)

- Baseline (local, no network): recolor the user's own hair to gold with a luminance-preserving LUT, using the hair
  class of the MediaPipe multiclass selfie segmenter, run only while transformed and at low rate (5 Hz). Add spikes as
  a sprite anchored to the face landmarks (forehead top `10`, face width `234/454`, roll from the eye line), drawn
  behind the head where the mask allows.
- Personalised hair (opt-in, needs network or a local GPU **once**): during setup take one photo, ask an image-edit
  model for "this person as Super Saiyan", segment the hair of the generated image, and at runtime warp that hair
  layer onto the head with a similarity transform from the face landmarks. Generate front and two three-quarter
  views to survive head turns. This breaks the "nothing leaves your computer" promise: it must be explicitly opt-in,
  documented, and off by default. **Ask the owner before adding any network call** (AGENTS.md: no network connections
  other than model downloads).
- Not recommended: real-time full-frame AI stylization (StreamDiffusion & co.) — needs a strong GPU, flickers, does
  not run on a laptop CPU.

### 4.5 Acceptance for the visual work

- Synthetic-mask tests: the aura never writes inside the person mask; the rim light never changes pixels outside a
  band inside the edge; the result is deterministic for a fixed `t`.
- Owner review on a real call (Meet, background effects off), light wall and dark room. Ask for a screenshot.

## 5. Performance: diagnosis

Budget at 30 FPS: **33 ms per frame**. Everything runs **serially in one thread**: capture → hand+face detection →
segmentation → effect → preview → virtual camera.

| Step | Cost (ALGORITHMS.md, blank frames) | Rate | CPU |
|---|---|---|---|
| Hand + face landmarkers | ~30.5 ms | 12.5 Hz | ~38 % of a core, always, even when idle |
| Aura | ~11–13.6 ms | **every frame** (30 Hz) | ~40 % of a core |
| Person segmenter | ~6 ms | 10 Hz | ~6 % |
| Capture/decode, color conversion, preview, virtual cam | not measured (estimate 5–8 ms) | every frame | estimate 15–25 % |

Problems:

1. **Jank:** on frames where detection runs, detection + aura + the rest ≈ 50 ms > 33 ms, so a frame is lost about every
   80 ms. Average FPS can look fine while motion stutters.
2. **Wasted work:** the aura recomputes its whole geometry 30 times per second although its input mask changes 10 times
   per second; detection runs at full rate when nobody is gesturing.
3. **Measurements are on blank frames**, where the palm detector behaves differently from a real person. They are a
   lower bound.

**Language:** Python is fine. MediaPipe and OpenCV are native and release the GIL; Python glue is not the bottleneck.
Do not rewrite in C++/Rust. Later, optional: a small native extension for the aura pixel maths if profiling still
shows it, or running the same models through OpenVINO/ONNX Runtime with int8 weights for thread control.

## 6. Performance plan (in order)

0. **Benchmark harness first.** Add `--input-video PATH` (read frames from a file instead of the camera; no writing to
   disk, see AGENTS.md) and a `--bench` mode that prints per-stage p50/p95 times and process CPU % over N frames.
   The owner records a short clip themselves (idle, teleport, charge, transformed, moving). Add a CI check on a tiny
   synthetic clip that fails on large regressions of the pure-Python/OpenCV stages.
1. **Threads instead of a serial loop.**
   - Capture thread keeps only the latest frame (drop stale ones).
   - Inference in the background with MediaPipe `RunningMode.LIVE_STREAM` + `detect_async`/`segment_async` and
     result callbacks; the render loop never waits for a model and uses the latest result. Keep timestamps strictly
     increasing per task. Keep the patchable seams in AGENTS.md working (tests drive the loop with a fake clock).
   - Expected: steady 30 FPS; 30–60 ms extra detection latency, invisible for gestures held 1–1.5 s.
2. **Activity-adaptive detection** (biggest saving in a normal call).
   - No hands seen: detect at 4–5 Hz; hand present: 12–15 Hz; during a hold: full rate.
   - Cheap motion gate before that: abs diff of 64×36 grayscale thumbnails; no motion → skip the model.
   - Face landmarker only when a hand is near the head; otherwise reuse the last face (already done for the charge).
     The teleport still needs a fresh face when the fingers reach the forehead.
   - Expected idle CPU for detection: ~38 % → ~10 % of a core (estimate).
3. **Aura: compute geometry per mask update, not per frame.**
   - Cache distance transform, ring, rising field, contour/edge points and (later) the remap maps; per frame only scroll
     the noise / pick the strip frame, color and blend.
   - uint8 maths: `cv2.LUT`, saturating `cv2.add`/screen blend; avoid full-ROI float32 arrays; precompute the noise at
     the max size and crop instead of resizing every frame.
   - Expected: ~11 ms → 3–4 ms per frame (estimate). Keep `test_fast_enough_for_live_video`.
4. **Prototype a single-model cascade** (only after 0–3, behind a flag): `pose_landmarker_lite` gives wrists, rough
   fingers, nose and eyes **and** a segmentation mask in one pass. It could replace the segmenter and act as the first
   stage; run the fine hand landmarker only on a crop around the head when wrists are near it. This touches the
   gesture detection that works today: compare on the owner's recorded clip before adopting.
5. **Smaller items:** preview window at 15 FPS (virtual camera stays at 30); make sure the camera delivers the working
   resolution directly (no 1080p decode + resize); `apply_dissolve` to uint8 and ROI-only; vectorize or cache
   `speed_lines`.

Expected outcome of 1–3 (estimate, to confirm with the harness on the owner's machine): transformed from >1 core with
jank to ~0.4–0.5 core at a steady 30 FPS; idle ~0.15 core.

## 7. Order of work

See §E. The visible problems in the owner's screenshot are cheap to fix, so the visual foundations (E1) go before
the benchmark harness (E2); E1 only touches the aura path and must not slow the loop down.

## 8. Stop and ask the owner when

- a change would alter the gesture thresholds or how the poses are detected;
- you want to add any network call, a new model download, or a new dependency (license check, NOTICE.md, lock file);
- you need hardware verification (real camera, Meet/Zoom, Windows/macOS);
- you want to touch the CI matrix or GitHub settings (macOS arm64 runner issue).
