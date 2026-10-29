# Handoff — what is left to fix and finish

State as of 2026-10-29 (main around `312e551`). Read `AGENTS.md` first: layout, loop phases, rules and testable seams.

## Status

| Area | State |
|---|---|
| Modes | Dragon Ball (default) + Super Saiyan, Normal, Naruto. All covered by unit tests (80). **Never tried with a real webcam.** |
| CI (`.github/workflows/tests.yml`) | ubuntu-latest ✅, windows-latest ✅, macos-15-intel ✅ (MediaPipe 0.10.14), macos-latest (arm64) ✅ (MediaPipe 1.2.0). Installs from `requirements.lock.txt` with `--require-hashes`. |
| Ubuntu installer | Rewritten for the owner's machine (22.04, HWE kernel 6.8, Secure Boot likely). **Not yet run on real hardware** after the rewrite. `uninstall-ubuntu.sh` exists and is syntax-checked only. |
| Windows / macOS installers | `install.ps1` / `install.sh`. Only syntax-checked; never run end to end on a real machine. |
| Packaging | `VanishCam.spec` updated (face + multiclass models, new modules); `VanishCam.macos.spec` + `BUILD_MACOS.sh` added. Both **untested**. |
| Language | Everything is English (code, messages, docs). Keep it that way. |
| Licensing | Upstream (Nicovic17/vanish_webcam) has **no license**. Commit `2a72169` added LICENSE (MIT for this fork's contributions only, with a scope paragraph), NOTICE.md (per-file upstream/fork split, third-party licenses), CHANGELOG, CONTRIBUTING, CODE_OF_CONDUCT, SECURITY and issue/PR templates. Keep NOTICE.md and CHANGELOG.md up to date. |

## 1. macOS arm64 crash — resolved

MediaPipe 1.0.1 aborted on Apple silicon while opening the gesture/hand tasks:

```
F0000 graph_service.h:139] Check failed: service_ Service is unavailable.
  -[DrishtiMetalHelper initWithCalculatorContext:]
  mediapipe::api2::TensorsToDetectionsCalculator::Open()
```

A CI probe on `macos-latest` (1.0.1, 1.1.0, 1.2.0 and 0.10.14, running `--self-test`) gave: 1.0.1 ❌,
1.1.0 ✅, 1.2.0 ✅, 0.10.14 ✅. Upstream PR Nicovic17/vanish_webcam#2 reports the same crash on real Apple
silicon and also fixes it with 1.1.1. `requirements.txt` now pins **1.2.0** everywhere except Intel Macs, and the
full CI matrix is green. Intel Macs keep MediaPipe 0.10.14 (no 1.x x86_64 wheels).

Still unverified: audio on macOS. OpenCV and pygame each bundle their own `libSDL2-2.0.0.dylib`, so the logs show
`Class SDLApplication is implemented in both … may cause mysterious crashes`. Upstream PR #4 plays sounds with
`afplay`, but that loses looping (`play(loops=-1)`, used by the Super Saiyan aura) and volume control; do not adopt
it without a wrapper. Watch for crashes when sound plays on real hardware.

## 2. Verify with real hardware (owner)

Nothing has run against a real webcam. Tunables to adjust once someone tries it:

- **Dragon Ball gesture** (`dragonball_effect.py`): finger straightness `0.8`, tips together `< 0.5 × finger length`, forehead distance `< 0.38 × face width`, hold `1.0 s`.
- **Super Saiyan** (`super_saiyan_effect.py`): fists `ratio < 0.75`, reach `< 1.15 × knuckle`, 3 of 4 fingers; hand size `0.25–0.9 × face width`; wrists below `chin + 0.5 × face width`; `> 0.35 × face width` from the nose; `AURA_RADIUS = 16`, flame gain `1.3`, noise speed `220 px/s`; hair threshold `(m - 0.35) / 0.4`; `CHARGE_SECONDS 1.5`, `FLASH_SECONDS 0.45`, `POWER_DOWN_SECONDS 0.6`.
- **Background capture**: 1.5 s sampling, person-area limit 2 %.
- Use `--gesture-debug` to see what is detected.
- CPU cost of Super Saiyan (multiclass segmenter at 10 Hz) on older laptops: measure; lower the rate if a frame takes > 40 ms.

## 3. Ubuntu installer on the owner's PC

- Owner: Ubuntu 22.04, kernel `6.8.0-138-generic`, Python 3.10.6, broken third-party apt repo (yarn NO_PUBKEY). First run failed building `v4l2loopback-dkms` 0.12.7; the package was left half-configured.
- `install-ubuntu.sh` now purges that package, skips the distro package on kernels ≥ 6.8, builds upstream v4l2loopback 0.13.2 (pinned commit), handles Secure Boot (MOK create/sign/enroll, reboot instructions), installs `libgles2`, and installs Python even if the camera fails.
- **Unverified:** that 0.13.2 really builds on 6.8 (deduced from source), the Secure Boot path (`mokutil`, MOK manager), DKMS signing of `.ko.zst` modules. Ask the owner for the terminal output from the last `[VanishCam]` line if it fails.
- `uninstall-ubuntu.sh` removes `/etc/modules-load.d/vanishcam.conf`, `/etc/modprobe.d/vanishcam.conf`, the DKMS
  module the installer built (only when no distro package owns it), the loaded module and the `.desktop` file. It
  keeps the app folder, `.venv`, `models/` and the MOK key (shared with other modules); verify on hardware.

## 4. Effect sounds in calls on Windows / macOS

- Linux: done (`./vanishcam.sh --call-audio` builds a PulseAudio/PipeWire virtual mic `VanishCam-Mic` = real mic + effects).
- Windows/macOS: `--audio-device NAME` is passed to `pygame.mixer.init(devicename=...)`. The README documents VB-Cable
  (Windows, with "Listen to this device" for the real mic) and BlackHole + an Aggregate/Multi-Output Device (macOS).
  Zoom/Meet noise suppression must be lowered. **Unverified on real hardware**, and the `ffplay` fallback ignores it.

## 5. Security audit leftovers (all low/medium)

- One-line installers still default to `main`: publish tagged releases and change the documented one-liner to a tag.
  They now accept `VANISHCAM_REF` (tag or commit), download the uv installer from a versioned release URL and verify
  its SHA-256 before running it.
- ~~No lock file~~: `requirements.lock.txt` is generated with `--universal --generate-hashes`; installers and CI use
  `--require-hashes`. Regenerate after every `requirements.txt` change.
- ~~Segmenter URL uses `latest`~~: all model URLs are versioned (`/1/`) and the hashes were re-verified.
- `install.sh` / `install.ps1` copy a new download over an old install without deleting removed files (still true).

## 6. Smaller items

- *Particles* mode from the upstream README was never implemented.
- `VanishCam.spec` was updated for the new models/modules but still untested; `VanishCam.macos.spec` /
  `BUILD_MACOS.sh` (a `.app` build) were added, also untested. Build both on real machines before shipping binaries.
- Ask the upstream author to add a license (owner's decision; don't contact anyone without asking).
- pyvirtualcam is **GPL-2.0**: fine for the MIT source (users install it from PyPI), but any packaged binary (PyInstaller `.exe`) that bundles it must comply with GPL-2.0, or pyvirtualcam must be replaced. See NOTICE.md.
- ~~Owner action: enable "Private vulnerability reporting"~~: enabled on 2026-10-29.
- GitHub may not detect LICENSE as MIT because of its scope paragraph. If that matters, keep LICENSE as plain MIT and move the scope note to NOTICE.md/README only. The owner has not decided this yet; leaving the scope paragraph is the legally accurate option.
- ~~CHANGELOG entries without a commit hash~~: filled in from `git log`.

### Upstream pull requests (reviewed 2026-10-29, all still open, none merged)

Upstream has three open PRs against `Nicovic17/vanish_webcam`. Read them for ideas, but do **not** copy their code:
upstream has no license, so neither does the code in its PRs (see `NOTICE.md`).

- **#1 (Linux + English):** native V4L2 capture, `v4l2loopback`, `run_*.sh` launchers and an English rewrite. This
  fork already covers all of it (`open_camera`, `install-ubuntu.sh`, `vanishcam.sh`, `dcc9c90`); nothing to port.
- **#2 (macOS):** confirms the MediaPipe arm64 crash on real hardware and fixes it with 1.1.1 (this fork uses 1.2.0,
  verified in CI). Also proposes `default_virtual_backend()` (obs on macOS, v4l2loopback on Linux); pyvirtualcam
  already auto-selects correctly, so it is optional. Adds `avvia_*.sh` launchers, superseded by `vanishcam.sh`.
- **#4 (macOS build):** adds `VanishCam.macos.spec` + `BUILD_MACOS.sh` (a `.app` build this repo still lacks) and plays
  sounds with `afplay`. The afplay idea avoids the duplicate-SDL2 issue but drops looping and volume, which the
  Super Saiyan aura needs. The macOS `.app` target is worth reimplementing independently when someone has a Mac.

## Dev environment notes

- Tests: `.venv/bin/python -m unittest discover -p 'test_*.py'`; Linux needs `libegl1 libgles2`.
- MediaPipe tasks crash with `malloc(): unaligned tcache chunk` in headless containers without a GPU/display (seen on the claude-bcn LXC) — this is the environment, not the app; Ubuntu CI runs them fine. Rely on CI for `--self-test`.
- After changing `.bat`/`.ps1`, keep them pure ASCII (Windows PowerShell 5.1 reads BOM-less files as ANSI); `.gitattributes` forces CRLF for them.
